"""核心编排智能体（orchestrator）：唯一任务入口，委派子智能体并行/串行协作并汇总。

- think 节点：携带「可用子智能体 + 工具」清单请求 LLM，流式输出（转 agent:think）；
- 输出含 {"tool_calls": [...]} 时，tool 节点解析并并行执行（受 subagent_max_concurrency 限制）；
- 有先后依赖的委派由模型分轮次完成（先拿到前一轮结果回注，再 think 委派下一批）；
- 无工具调用即结束，最后一条 assistant 消息为最终答案。
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from nvwa_agent.config import get
from nvwa_agent.core import taskctx
from nvwa_agent.sdk import BaseAgentPlugin, PluginContext

_MAX_TOOL_ROUNDS = 8


class AgentState(TypedDict):
    messages: list
    tool_rounds: int


class OrchestratorAgentPlugin(BaseAgentPlugin):
    system_prompt = (
        "你是 NvwaAgent 核心编排智能体。你接收用户请求，判断是否需要委派给专业子智能体协作完成，"
        "并汇总各子智能体结果，输出最终答案。全程使用中文。规则：\n"
        "1) 简单请求可直接回答；需要专业能力（记账、写作、知识复盘、代码、整理等）时委派给对应子智能体。\n"
        "2) 可一次委派多个互不依赖的子智能体（并行）；有先后依赖的，等前一个结果返回后再委派下一个（分轮）。\n"
        "3) 委派时给子智能体清晰、自包含的任务描述（prompt），不要假设子智能体知道上下文。\n"
        "4) 汇总子智能体结果时保持信息完整、不编造；如子智能体失败，可重试或基于已有结果给出答案。\n"
        "如需委派子智能体，请在回复中单独输出一行 JSON：\n"
        '{"tool_calls": [{"tool_id": "子智能体id", "args": {"prompt": "任务描述"}}, ...]}\n'
        "否则直接给出最终答案（不要输出任何工具JSON）。"
    )

    def build_graph(self, ctx: PluginContext):
        def _tools_brief(state: AgentState) -> str:
            specs = []
            try:
                from nvwa_agent.core.plugin_runtime.runtime import get_runtime
                specs = get_runtime().tool_specs_for(ctx.plugin_id)
            except Exception:
                specs = []
            if not specs:
                return "（当前无可用子智能体或工具）"
            lines = [f'- {s["tool_id"]}: {s["description"]} 参数: {json.dumps(s["parameters_schema"], ensure_ascii=False)}' for s in specs]
            return "\n".join(lines)

        def think(state: AgentState) -> dict:
            messages = list(state["messages"])
            system = self.system_prompt + "\n可用子智能体/工具：\n" + _tools_brief(state)
            messages[0] = {"role": "system", "content": system}
            chunks = ctx.llm.chat(messages, stream=True)
            answer = "".join(chunks)
            return {"messages": messages + [{"role": "assistant", "content": answer}]}

        def wants_tool(state: AgentState) -> str:
            rounds = state.get("tool_rounds", 0)
            if rounds >= _MAX_TOOL_ROUNDS:
                return "final"
            last = state["messages"][-1]
            return "tool" if _extract_tool_calls(last.get("content", "")) else "final"

        def tool_node(state: AgentState) -> dict:
            rounds = state.get("tool_rounds", 0)
            last = state["messages"][-1]
            calls = _extract_tool_calls(last.get("content", "")) or []
            # 主线程拿到正确 task_id，供并行 worker 线程重新绑定任务上下文
            current_task = taskctx.get_current_task()
            concurrency = max(1, int(get("subagent_max_concurrency", 3)))

            def run_one(call):
                taskctx.set_current_task(current_task)
                tool_id = call.get("tool_id", "")
                args = call.get("args") or {}
                try:
                    result = ctx.tools.call(tool_id, args)
                    observation = json.dumps(result, ensure_ascii=False)[:4000]
                except Exception as exc:
                    observation = f"调用失败: {exc}"
                return tool_id, observation

            results = {}
            if len(calls) <= 1:
                for call in calls:
                    tid, obs = run_one(call)
                    results[tid] = obs
            else:
                workers = min(concurrency, len(calls))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    for tid, obs in ex.map(run_one, calls):
                        results[tid] = obs

            observation = json.dumps(results, ensure_ascii=False)[:4000]
            return {
                "messages": state["messages"] + [{"role": "user", "content": f"子智能体结果：{observation}"}],
                "tool_rounds": rounds + 1,
            }

        def final_answer(state: AgentState) -> dict:
            return {"tool_rounds": state.get("tool_rounds", 0)}

        graph = StateGraph(AgentState)
        graph.add_node("think", think)
        graph.add_node("tool_call", tool_node)
        graph.add_node("final_answer", final_answer)
        graph.add_edge(START, "think")
        graph.add_conditional_edges("think", wants_tool, {"tool": "tool_call", "final": "final_answer"})
        graph.add_edge("tool_call", "think")
        graph.add_edge("final_answer", END)
        return graph.compile()


def _extract_tool_calls(text: str) -> list[dict] | None:
    """提取一轮 think 中的 tool_calls（兼容 tool_call 单对象与 tool_calls 数组）。"""
    if not text:
        return None
    data = _find_json(text)
    if data is None:
        return None
    if isinstance(data.get("tool_calls"), list):
        return [c for c in data["tool_calls"] if isinstance(c, dict)]
    if isinstance(data.get("tool_call"), dict):
        return [data["tool_call"]]
    return None


def _find_json(text: str) -> dict | None:
    """从文本中定位并解析一个平衡的 JSON 对象（取第一个 '{' 到匹配的 '}'）。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except (ValueError, TypeError):
                    return None
    return None


def on_load(ctx: PluginContext) -> BaseAgentPlugin:
    ctx.logger.info("核心编排智能体插件加载")
    return OrchestratorAgentPlugin()


def on_activate(ctx: PluginContext) -> None:
    ctx.logger.info("核心编排智能体插件激活")


def on_deactivate(ctx: PluginContext) -> None:
    ctx.logger.info("核心编排智能体插件禁用")


def on_unload(ctx: PluginContext) -> None:
    ctx.logger.info("核心编排智能体插件卸载")
