"""Agent 执行（LangGraph 编排，§10）。

- 插件图状态约定：state["messages"] 为 OpenAI 风格消息列表（SDK 文档约束）；
- 最终答案取图执行结束后最后一条 assistant 消息内容 -> task_record.result。
"""
import time

from nvwa_agent.config import get_task_limits
from nvwa_agent.core.plugin_runtime.event_bus import event_bus


def run_agent_graph(meta, instance, graph, prompt: str, task_id: str,
                    file_ids: list[str] | None = None) -> str:
    """调用选中Agent的 StateGraph 并返回最终完整答案。"""
    _, max_calls = get_task_limits()
    user_content = prompt
    if file_ids:
        user_content += f"\n（用户提供了附件文件id: {file_ids}，可通过工具访问 data/uploads 目录）"

    state = {
        "messages": [
            {"role": "system", "content": getattr(instance, "system_prompt", "") or ""},
            {"role": "user", "content": user_content},
        ]
    }
    event_bus.publish("task:update", {
        "task_id": task_id, "status": "running",
        "step_desc": f"Agent「{meta.name}」执行中",
    }, task_id=task_id)

    started = time.time()
    final_state = graph.invoke(state, config={"recursion_limit": max_calls * 2 + 10})

    messages = (final_state or {}).get("messages") or []
    answer = ""
    for msg in reversed(messages):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        if role in ("assistant", "ai") and content:
            answer = content if isinstance(content, str) else str(content)
            break
    if not answer:
        answer = f"（Agent「{meta.name}」未产出最终答案，耗时 {round(time.time() - started, 1)}s）"
    return answer
