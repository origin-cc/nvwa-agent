"""文档写作Agent插件：文章生成、文案撰写、润色改写、格式排版（ReAct 单循环图）。

- think 节点：携带可用工具清单请求 LLM，流式输出（运行时自动转 agent:think）；
- 先确认文体/受众/语气/篇幅，再产出完整成稿；支持润色与改写（保留原意优化表达）；
- 用户要求保存成稿时调用 file-write-tool:write_text 保存至 data/generated_docs/（.md/.txt 按需）；
- 输出包含 {"tool_call": {...}} 时进入 tool 节点执行后回到 think；
- 无工具调用即结束，最后一条 assistant 消息为最终答案。
"""
import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from nvwa_agent.sdk import BaseAgentPlugin, PluginContext

_MAX_TOOL_ROUNDS = 5


class AgentState(TypedDict):
    messages: list
    tool_rounds: int


class PersonalWritingAgentPlugin(BaseAgentPlugin):
    system_prompt = (
        "你是 NvwaAgent 文档写作智能体，一位专业的中文写作助手，"
        "擅长文章生成、文案撰写、润色改写与格式排版。\n"
        "工作流程：\n"
        "1. 动笔前先确认文体（邮件/文章/文案等）、受众、语气与篇幅；信息不明确时先向用户简要确认，"
        "用户已给出足够信息时可直接成稿；\n"
        "2. 润色与改写需求需保留原意、优化表达；\n"
        "3. 用户要求保存成稿时，调用工具 file-write-tool:write_text 保存至 data/generated_docs/ 目录"
        "（.md/.txt 按需）；\n"
        "4. 输出排版清晰：使用标题、段落与列表组织内容。\n"
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
    ctx.logger.info("文档写作Agent插件加载")
    return PersonalWritingAgentPlugin()


def on_activate(ctx: PluginContext) -> None:
    ctx.logger.info("文档写作Agent插件激活")


def on_deactivate(ctx: PluginContext) -> None:
    ctx.logger.info("文档写作Agent插件禁用")


def on_unload(ctx: PluginContext) -> None:
    ctx.logger.info("文档写作Agent插件卸载")
