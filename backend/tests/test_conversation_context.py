"""会话上下文记忆测试：历史重建、滚动摘要折叠、Agent 注入。"""
from datetime import datetime
from types import SimpleNamespace

from nvwa_agent.core.scheduler import context as context_mod
from nvwa_agent.core.scheduler.agent_runner import run_agent_graph
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import Conversation, TaskRecord


def _create_conversation(conv_id: str) -> None:
    with session_scope() as db:
        db.add(Conversation(conversation_id=conv_id, title="t"))


def _add_task(conv_id, task_id, status, user, assistant, created_at) -> None:
    with session_scope() as db:
        db.add(TaskRecord(
            task_id=task_id,
            conversation_id=conv_id,
            status=status,
            input_prompt=user,
            result=assistant,
            created_at=created_at,
        ))


def _t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute)


def test_load_finished_turns_filters_and_excludes():
    _create_conversation("ctx-c1")
    _add_task("ctx-c1", "c1-t1", "finish", "u1", "r1", _t(10, 0))
    _add_task("ctx-c1", "c1-t2", "pending", "u2", None, _t(10, 1))
    _add_task("ctx-c1", "c1-t3", "finish", "u3", "", _t(10, 2))
    _add_task("ctx-c1", "c1-t4", "finish", "u4", "r4", _t(10, 3))
    turns = context_mod.load_finished_turns("ctx-c1", exclude_task_id="c1-t4")
    assert [t.task_id for t in turns] == ["c1-t1"]


def test_load_finished_turns_orders_by_time():
    _create_conversation("ctx-c2")
    _add_task("ctx-c2", "c2-a", "finish", "uA", "rA", _t(10, 2))
    _add_task("ctx-c2", "c2-b", "finish", "uB", "rB", _t(10, 0))
    _add_task("ctx-c2", "c2-c", "finish", "uC", "rC", _t(10, 1))
    turns = context_mod.load_finished_turns("ctx-c2", exclude_task_id="zzz")
    assert [t.task_id for t in turns] == ["c2-b", "c2-c", "c2-a"]


def test_expand_turns():
    turns = [context_mod.Turn("x", "u", "a")]
    assert context_mod.expand_turns(turns) == [
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]


def test_build_context_within_window_no_summary():
    _create_conversation("ctx-c3")
    _add_task("ctx-c3", "c3-a", "finish", "u1", "r1", _t(10, 0))
    _add_task("ctx-c3", "c3-b", "finish", "u2", "r2", _t(10, 1))
    msgs = context_mod.build_conversation_context("ctx-c3", exclude_task_id="cur",
                                                  window_chars=1000, retain_ratio=0.2)
    assert msgs == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "r2"},
    ]


def test_build_context_short_content_no_compress():
    """内容短（token 少）时不压缩，全部原文注入。"""
    _create_conversation("ctx-c7")
    for i in range(4):
        _add_task("ctx-c7", f"c7-t{i}", "finish", f"u{i}", f"r{i}", _t(10, i))
    # 4 轮仅 16 字符，远小于窗口，不压缩
    msgs = context_mod.build_conversation_context("ctx-c7", exclude_task_id="cur",
                                                  window_chars=1000, retain_ratio=0.2)
    assert msgs == [
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "r0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "r2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "r3"},
    ]
    from nvwa_agent.models.task import ConversationSummary
    with session_scope() as db:
        assert db.get(ConversationSummary, "ctx-c7") is None


def test_build_context_over_window_replaces(monkeypatch):
    """超窗口：保留最近 retain 预算的原文，其余整体替换为摘要。"""
    _create_conversation("ctx-c5")
    _add_task("ctx-c5", "c5-t0", "finish", "u" * 20, "r" * 20, _t(10, 0))
    _add_task("ctx-c5", "c5-t1", "finish", "u" * 20, "r" * 20, _t(10, 1))
    _add_task("ctx-c5", "c5-t2", "finish", "u" * 20, "r" * 20, _t(10, 2))

    calls = []

    def fake(prev, new):
        calls.append((prev, [t.task_id for t in new]))
        return "S"

    monkeypatch.setattr(context_mod, "_summarize", fake)
    # 3 轮 × 40 字符 = 120 > 窗口 100；retain 预算 20 → 保留最新 1 轮，折叠前 2 轮
    msgs = context_mod.build_conversation_context("ctx-c5", exclude_task_id="cur",
                                                  window_chars=100, retain_ratio=0.2)
    assert calls == [("", ["c5-t0", "c5-t1"])]
    assert msgs == [
        {"role": "user", "content": "【对话历史摘要】\nS"},
        {"role": "user", "content": "u" * 20},
        {"role": "assistant", "content": "r" * 20},
    ]


def test_build_context_incremental_sawtooth(monkeypatch):
    """锯齿式压缩：压缩后可见上下文回落，不会每轮重复压缩。"""
    _create_conversation("ctx-c8")
    _add_task("ctx-c8", "c8-t0", "finish", "u" * 20, "r" * 20, _t(10, 0))
    _add_task("ctx-c8", "c8-t1", "finish", "u" * 20, "r" * 20, _t(10, 1))
    _add_task("ctx-c8", "c8-t2", "finish", "u" * 20, "r" * 20, _t(10, 2))

    calls = []

    def fake(prev, new):
        calls.append([t.task_id for t in new])
        return "S"

    monkeypatch.setattr(context_mod, "_summarize", fake)
    # 3 轮（120 字符）超窗口，压缩折叠 t0/t1，保留 t2
    context_mod.build_conversation_context("ctx-c8", exclude_task_id="cur",
                                           window_chars=100, retain_ratio=0.2)
    assert calls == [["c8-t0", "c8-t1"]]

    # 4 轮：摘要"S"(1) + t2/t3(80) = 81 ≤ 100，不压缩
    _add_task("ctx-c8", "c8-t3", "finish", "u" * 20, "r" * 20, _t(10, 3))
    context_mod.build_conversation_context("ctx-c8", exclude_task_id="cur",
                                           window_chars=100, retain_ratio=0.2)
    assert len(calls) == 1

    # 5 轮：摘要"S"(1) + t2/t3/t4(120) = 121 > 100，再次压缩折叠 t2/t3
    _add_task("ctx-c8", "c8-t4", "finish", "u" * 20, "r" * 20, _t(10, 4))
    context_mod.build_conversation_context("ctx-c8", exclude_task_id="cur",
                                           window_chars=100, retain_ratio=0.2)
    assert calls[-1] == ["c8-t2", "c8-t3"]


def test_build_context_summary_failure_falls_back(monkeypatch):
    _create_conversation("ctx-c6")
    _add_task("ctx-c6", "c6-t0", "finish", "u" * 20, "r" * 20, _t(10, 0))
    _add_task("ctx-c6", "c6-t1", "finish", "u" * 20, "r" * 20, _t(10, 1))
    _add_task("ctx-c6", "c6-t2", "finish", "u" * 20, "r" * 20, _t(10, 2))
    monkeypatch.setattr(context_mod, "_summarize", lambda prev, new: None)
    # 摘要失败：待折叠轮次与保留轮次一并原文注入，零丢失
    msgs = context_mod.build_conversation_context("ctx-c6", exclude_task_id="cur",
                                                  window_chars=100, retain_ratio=0.2)
    assert msgs == [
        {"role": "user", "content": "u" * 20},
        {"role": "assistant", "content": "r" * 20},
        {"role": "user", "content": "u" * 20},
        {"role": "assistant", "content": "r" * 20},
        {"role": "user", "content": "u" * 20},
        {"role": "assistant", "content": "r" * 20},
    ]


class _FakeGraph:
    def __init__(self):
        self.captured = None

    def invoke(self, state, config=None):
        self.captured = state
        return {"messages": state["messages"] + [{"role": "assistant", "content": "ok"}]}


def test_run_agent_graph_injects_history():
    graph = _FakeGraph()
    meta = SimpleNamespace(name="test-agent")
    instance = SimpleNamespace(system_prompt="SYS")
    history = [
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "r0"},
    ]
    answer = run_agent_graph(meta, instance, graph, "hi", "task-1", history=history)
    assert answer == "ok"
    assert graph.captured["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "r0"},
        {"role": "user", "content": "hi"},
    ]
