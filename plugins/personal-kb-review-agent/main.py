"""知识复盘智能体插件：知识库文档总结/复盘/问答（ReAct 单循环图，§10）。

- 人设：严谨的知识复盘助手，答案必须基于知识库检索到的原文片段；
- 回答任何基于用户资料的问题前，必须先调用 kb-retrieval-tool:search 检索，
  支持用完整自然语言 query 从多个角度多次检索；
- think 节点：携带可用工具清单请求 LLM，流式输出（运行时自动转 agent:think）；
- 输出包含 {"tool_call": {...}} 时进入 tool 节点执行后回到 think；
- 无工具调用即结束，最后一条 assistant 消息为最终答案。
"""
import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from nvwa_agent.sdk import BaseAgentPlugin, PluginContext

_MAX_TOOL_ROUNDS = 8


class AgentState(TypedDict):
    messages: list
    tool_rounds: int


class PersonalKbReviewAgentPlugin(BaseAgentPlugin):
    system_prompt = (
        "你是「知识复盘智能体」，一位严谨的知识复盘助手，"
        "负责对用户上传的知识库文档进行内容总结、要点复盘、知识提炼与知识问答。\n"
        "工作规则：\n"
        "1. 回答任何基于用户资料的问题前，必须先调用知识库检索工具 kb-retrieval-tool:search 检索；\n"
        "2. 检索时使用完整自然语言 query（不要只用关键词），"
        "若一次检索覆盖不全，可换不同角度多次检索；\n"
        "3. 答案必须基于检索返回的原文片段，并标注来源文件名（如「来源：xxx.pdf」），"
        "严禁编造未在片段中出现的内容；\n"
        "4. 若知识库为空或检索不到相关内容，明确告知用户先上传文档，不要凭空作答；\n"
        "5. 回答最后给出结构化总结，以要点列表形式呈现。\n"
        "如需调用工具，请在回复中单独输出一行 JSON：\n"
        '{"tool_call": {"tool_id": "工具id", "args": {参数}}}\n'
        "否则直接给出最终答案（不要输出任何工具JSON）。"
    )

    def build_graph(self, ctx: PluginContext):
        def _tools_brief(state: AgentState) -> str:
            specs = ctx.tools and None
            try:
                from nvwa_agent.core.plugin_runtime.runtime import get_runtime
                specs = get_runtime().tool_specs_for(ctx.plugin_id)
            except Exception:
                specs = []
            if not specs:
                return "（当前无可用工具）"
            lines = [f'- {s["tool_id"]}: {s["description"]} 参数: {json.dumps(s["parameters_schema"], ensure_ascii=False)}' for s in specs]
            return "\n".join(lines)

        def think(state: AgentState) -> dict:
            messages = list(state["messages"])
            system = self.system_prompt + "\n可用工具：\n" + _tools_brief(state)
            messages[0] = {"role": "system", "content": system}
            chunks = ctx.llm.chat(messages, stream=True)
            answer = "".join(chunks)
            return {"messages": messages + [{"role": "assistant", "content": answer}]}

        def wants_tool(state: AgentState) -> str:
            rounds = state.get("tool_rounds", 0)
            if rounds >= _MAX_TOOL_ROUNDS:
                return "final"
            last = state["messages"][-1]
            return "tool" if _extract_tool_call(last.get("content", "")) else "final"

        def tool_node(state: AgentState) -> dict:
            rounds = state.get("tool_rounds", 0)
            last = state["messages"][-1]
            call = _extract_tool_call(last.get("content", "")) or {}
            tool_id = call.get("tool_id", "")
            args = call.get("args") or {}
            try:
                result = ctx.tools.call(tool_id, args)
                observation = json.dumps(result, ensure_ascii=False)[:4000]
            except Exception as exc:
                observation = f"工具调用失败: {exc}"
            return {
                "messages": state["messages"] + [{"role": "user", "content": f"工具结果：{observation}"}],
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


def _extract_tool_call(text: str) -> dict | None:
    match = re.search(r'\{\s*"tool_call"', text or "")
    if not match:
        return None
    start = match.start()
    end = text.find("}", text.find('"args"', start))
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start:i + 1])
                except (ValueError, TypeError):
                    return None
                call = data.get("tool_call")
                return call if isinstance(call, dict) else None
    return None


def on_load(ctx: PluginContext) -> BaseAgentPlugin:
    ctx.logger.info("知识复盘智能体插件加载")
    return PersonalKbReviewAgentPlugin()


def on_activate(ctx: PluginContext) -> None:
    ctx.logger.info("知识复盘智能体插件激活")


def on_deactivate(ctx: PluginContext) -> None:
    ctx.logger.info("知识复盘智能体插件禁用")


def on_unload(ctx: PluginContext) -> None:
    ctx.logger.info("知识复盘智能体插件卸载")
