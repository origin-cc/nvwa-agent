"""agent:think 流式分片合并落库测试（§8 事件10）。

预期：SSE 逐片推送不受影响；session_event_log 中每个「任务·智能体·轮次」
仅一条 agent:think 记录，内容为整轮拼接结果。
"""
import json

from nvwa_agent.core.plugin_runtime.event_bus import EventBus
from nvwa_agent.core import taskctx
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import SessionEventLog


def _think_rows(task_id: str) -> list[dict]:
    with session_scope() as db:
        rows = (
            db.query(SessionEventLog)
            .filter(SessionEventLog.task_id == task_id,
                    SessionEventLog.event_type == "agent:think")
            .order_by(SessionEventLog.log_id.asc())
            .all()
        )
        return [json.loads(r.event_payload) for r in rows]


def _event_rows(task_id: str) -> list[tuple[str, dict]]:
    with session_scope() as db:
        rows = (
            db.query(SessionEventLog)
            .filter(SessionEventLog.task_id == task_id)
            .order_by(SessionEventLog.log_id.asc())
            .all()
        )
        return [(r.event_type, json.loads(r.event_payload)) for r in rows]


def _publish_think_turn(bus: EventBus, task_id: str, agent_id: str,
                        shards: list[str], final_seq: int | None = None) -> None:
    """模拟一轮完整思考流：逐片发布，最后发布 is_final 收尾事件。"""
    taskctx.set_current_task(task_id)  # 生产环境由任务 Worker 绑定当前任务上下文
    for i, shard in enumerate(shards, start=1):
        bus.publish("agent:think", {
            "task_id": task_id, "agent_id": agent_id, "seq": i,
            "is_final": False, "think_content": shard,
        }, task_id=task_id)
    bus.publish("agent:think", {
        "task_id": task_id, "agent_id": agent_id,
        "seq": final_seq if final_seq is not None else len(shards) + 1,
        "is_final": True, "think_content": "",
    }, task_id=task_id)


def test_think_shards_merged_into_one_row():
    bus = EventBus()
    _publish_think_turn(bus, "t1", "agent-a", ["你好", "，", "世界"])

    rows = _think_rows("t1")
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "agent-a"
    assert rows[0]["think_content"] == "你好，世界"
    assert rows[0]["is_final"] is True
    assert rows[0]["seq"] == 4  # 收尾事件的 seq


def test_tool_call_flushes_pending_think_before_itself():
    bus = EventBus()
    taskctx.set_current_task("t2")
    # 思考两片后直接调用工具（未发 is_final 也应收尾合并）
    bus.publish("agent:think", {
        "task_id": "t2", "agent_id": "agent-a", "seq": 1,
        "is_final": False, "think_content": "先想想",
    }, task_id="t2")
    bus.publish("agent:think", {
        "task_id": "t2", "agent_id": "agent-a", "seq": 2,
        "is_final": False, "think_content": "再想想",
    }, task_id="t2")
    bus.publish("tool:call", {
        "task_id": "t2", "tool_id": "finance-ledger-tool", "call_args": {},
    }, task_id="t2")

    events = _event_rows("t2")
    assert [t for t, _ in events] == ["agent:think", "tool:call"]
    think_payload = events[0][1]
    assert think_payload["think_content"] == "先想想再想想"
    assert think_payload["is_final"] is True


def test_two_turns_same_agent_produce_two_rows():
    bus = EventBus()
    taskctx.set_current_task("t3")
    # 第一轮思考 -> 工具调用 -> 第二轮思考收尾
    _publish_think_turn(bus, "t3", "agent-a", ["第一轮"])
    bus.publish("tool:call", {"task_id": "t3", "tool_id": "demo-file-tool", "call_args": {}},
                task_id="t3")
    _publish_think_turn(bus, "t3", "agent-a", ["第二轮"])

    rows = _think_rows("t3")
    assert len(rows) == 2
    assert [r["think_content"] for r in rows] == ["第一轮", "第二轮"]


def test_cancelled_task_flushes_partial_think():
    bus = EventBus()
    taskctx.set_current_task("t4")
    bus.publish("agent:think", {
        "task_id": "t4", "agent_id": "agent-a", "seq": 1,
        "is_final": False, "think_content": "半截",
    }, task_id="t4")
    # 流式被取消：无 is_final，任务生命周期事件兜底冲刷
    bus.publish("task:cancelled", {"task_id": "t4"}, task_id="t4")

    rows = _think_rows("t4")
    assert len(rows) == 1
    assert rows[0]["think_content"] == "半截"
    assert rows[0]["is_final"] is True


def test_heartbeat_does_not_split_ongoing_think():
    bus = EventBus()
    taskctx.set_current_task("t5")
    bus.publish("agent:think", {
        "task_id": "t5", "agent_id": "agent-a", "seq": 1,
        "is_final": False, "think_content": "第一片",
    }, task_id="t5")
    # 长思考期间的保活心跳（write_log=False）不应冲刷缓冲
    bus.publish_heartbeat()
    bus.publish("agent:think", {
        "task_id": "t5", "agent_id": "agent-a", "seq": 2,
        "is_final": False, "think_content": "第二片",
    }, task_id="t5")
    _publish_think_turn(bus, "t5", "agent-a", [], final_seq=3)

    rows = _think_rows("t5")
    assert len(rows) == 1
    assert rows[0]["think_content"] == "第一片第二片"
