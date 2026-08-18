"""意图识别解析与Agent挑选（§10）单元测试。"""
from types import SimpleNamespace

from nvwa_agent.core.scheduler.intent import IntentResult, _parse, pick_agent


def _agent(pid: str, priority: int = 0):
    meta = SimpleNamespace(plugin_id=pid, name=pid, description="", priority=priority)
    return (meta, None, None)


def _ids(result: IntentResult) -> list[str]:
    return [t[0].plugin_id for t in result.matched]


AGENTS = [_agent("agent-a", 1), _agent("agent-b", 5), _agent("agent-c", 3)]


def test_parse_standard_json():
    raw = ('{"intent": "问答", "matched_agent_ids": ["agent-a", "agent-b"], '
           '"subtasks": [{"agent_id": "agent-a", "description": "d"}]}')
    r = _parse(raw, "p", AGENTS)
    assert r.intent == "问答"
    assert _ids(r) == ["agent-a", "agent-b"]
    assert r.subtasks[0]["agent_id"] == "agent-a"


def test_parse_json_wrapped_in_text():
    """模型输出前后带说明文字时仍能提取 JSON。"""
    raw = '好的，调度结果如下：\n{"intent":"x","matched_agent_ids":["agent-c"]}\n以上。'
    r = _parse(raw, "p", AGENTS)
    assert _ids(r) == ["agent-c"]


def test_parse_selected_agent_variant():
    """兼容模型输出 selected_agent 单选变体（DeepSeek 实测）。"""
    raw = '{"intent":"x","selected_agent":"agent-b"}'
    r = _parse(raw, "p", AGENTS)
    assert _ids(r) == ["agent-b"]


def test_parse_matched_agents_variant():
    raw = '{"intent":"x","matched_agents":["agent-a"]}'
    r = _parse(raw, "p", AGENTS)
    assert _ids(r) == ["agent-a"]


def test_parse_matched_ids_as_string():
    raw = '{"intent":"x","matched_agent_ids":"agent-a"}'
    r = _parse(raw, "p", AGENTS)
    assert _ids(r) == ["agent-a"]


def test_parse_ignores_unknown_ids():
    raw = '{"intent":"x","matched_agent_ids":["agent-a","no-such"]}'
    r = _parse(raw, "p", AGENTS)
    assert _ids(r) == ["agent-a"]


def test_parse_garbage_yields_empty():
    r = _parse("模型抽风了，没有JSON", "p", AGENTS)
    assert r.matched == []
    assert r.intent == ""


def test_pick_agent_highest_priority():
    r = IntentResult("x", matched=AGENTS, subtasks=[])
    meta, _, _ = pick_agent(r)
    assert meta.plugin_id == "agent-b"  # priority=5 最大


def test_pick_agent_empty_returns_none():
    assert pick_agent(IntentResult("x", [], [])) is None
