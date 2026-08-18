"""智能记账理财分析智能体插件：日常记账、账目查询、消费统计分析、预算与理财建议（ReAct 单循环图）。

- think 节点：携带可用工具清单请求 LLM，流式输出（运行时自动转 agent:think）；
- 输出包含 {"tool_call": {...}} 时进入 tool 节点执行后回到 think；
- 无工具调用即结束，最后一条 assistant 消息为最终答案。
- 记账/查账/统计分析均通过 finance-ledger-tool:ledger 工具完成，禁止编造账目数据。
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


class PersonalFinanceAgentPlugin(BaseAgentPlugin):
    system_prompt = (
        "你是一名专业严谨的个人记账理财分析师。全程使用中文交流。严格遵守以下规则：\n"
        '1) 用户要求记账（记一笔/收入/支出）时，立即调用工具 finance-ledger-tool:ledger，'
        'args 形如 {"action":"add","amount":金额数字,"type":"income或expense","category":"分类",'
        '"note":"备注","date":"YYYY-MM-DD"(可选)}；'
        "金额从用户自然语言中提取，无法确定必填字段（金额/收支类型等）时先向用户追问，不要臆测。\n"
        '2) 用户要求查账/查账单时，调用 action="query"（可带 "month":"YYYY-MM" 或 "category" 过滤）。\n'
        '3) 用户要求消费分析/统计/预算建议时，先调用 action="stats"（可带 "month"）拿到真实数据，'
        "再基于工具返回结果做结构化分析：消费结构、异常支出、省钱建议、下月预算建议。\n"
        "4) 绝对禁止编造账目数据；所有金额结论必须来自工具返回结果；"
        "用户询问总体资产配置等通用理财知识时可直接回答，并提示仅供参考、非投资建议。\n"
        "5) 回复中所有金额保留两位小数。\n"
        "如需调用工具，请在回复中单独输出一行 JSON：\n"
        '{"tool_call": {"tool_id": "finance-ledger-tool:ledger", "args": {"action": "add", "amount": 25.50, '
        '"type": "expense", "category": "餐饮", "note": "午餐"}}}\n'
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
    ctx.logger.info("智能记账理财分析智能体插件加载")
    return PersonalFinanceAgentPlugin()


def on_activate(ctx: PluginContext) -> None:
    ctx.logger.info("智能记账理财分析智能体插件激活")


def on_deactivate(ctx: PluginContext) -> None:
    ctx.logger.info("智能记账理财分析智能体插件禁用")


def on_unload(ctx: PluginContext) -> None:
    ctx.logger.info("智能记账理财分析智能体插件卸载")
