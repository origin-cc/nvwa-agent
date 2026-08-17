"""意图识别与Agent匹配（§10 LLM交互协议，mock 模式含固定应答）。"""
import json

from nvwa_agent.core.llm import effective_llm_provider, get_llm_client
from nvwa_agent.core.plugin_runtime.event_bus import event_bus

_SYSTEM_PROMPT = "你是任务调度器，根据用户意图从可用Agent中选择最合适的Agent完成任务。只输出JSON。"


class IntentResult:
    def __init__(self, intent: str, matched: list, subtasks: list) -> None:
        self.intent = intent
        self.matched = matched          # [(meta, instance, graph)]
        self.subtasks = subtasks


def recognize(prompt: str, agents: list) -> IntentResult:
    """agents: [(meta, instance, graph)]（activated 状态）。"""
    if effective_llm_provider() == "mock":
        # 模拟模式（§10.5）：匹配全部 activated Agent，调度器仍按 priority 取最大
        return IntentResult(
            intent="[MOCK] 模拟意图识别",
            matched=list(agents),
            subtasks=[{"agent_id": m.plugin_id, "description": prompt[:80]} for m, _, _ in agents],
        )

    available = [
        {"agent_id": m.plugin_id, "name": m.name, "description": m.description,
         "priority": m.priority}
        for m, _, _ in agents
    ]
    user_payload = json.dumps(
        {"user_input": prompt, "available_agents": available}, ensure_ascii=False,
    )
    client = get_llm_client()
    raw = client.chat(
        [{"role": "system", "content": _SYSTEM_PROMPT},
         {"role": "user", "content": user_payload}],
        stream=False,
    )
    return _parse(str(raw), prompt, agents)


def _parse(raw: str, prompt: str, agents: list) -> IntentResult:
    by_id = {m.plugin_id: triple for triple in agents for m in [triple[0]]}
    data = {}
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
        except (ValueError, TypeError):
            data = {}
    matched_ids = data.get("matched_agent_ids") or []
    matched = [by_id[i] for i in matched_ids if i in by_id]
    subtasks = data.get("subtasks") or []
    return IntentResult(intent=data.get("intent", ""), matched=matched, subtasks=subtasks)


def pick_agent(result: IntentResult):
    """v0.1-alpha 单选模式：匹配集合中 priority 数值最大者（并列取先注册者）。"""
    if not result.matched:
        return None
    return max(result.matched, key=lambda t: t[0].priority)


def _notify_no_agent(task_id: str) -> None:
    event_bus.publish("task:error", {
        "task_id": task_id,
        "error_msg": "未匹配到任何可用Agent，请检查已启用插件",
        "error_code": "NO_AGENT_MATCHED",
    }, task_id=task_id)
