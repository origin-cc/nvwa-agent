"""核心编排测试：agent-as-tool、子 Agent 委派、orchestrator 工具调用解析。"""
import importlib.util
from pathlib import Path

from nvwa_agent.core import taskctx
from nvwa_agent.core.plugin_runtime import reconcile
from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.core.plugin_runtime.runtime import ORCHESTRATOR_ID, get_runtime


def _meta(pid: str, ptype: str = "backend_agent") -> PluginMeta:
    return PluginMeta(plugin_id=pid, name=pid, version="1.0.0", type=ptype)


class _FakeRuntime:
    def __init__(self, state: str):
        self.state = state
        self.activated = False

    def get_meta(self, pid: str):
        return _meta(ORCHESTRATOR_ID) if pid == ORCHESTRATOR_ID else None

    def get_state(self, pid: str) -> str:
        return self.state

    def activate(self, pid: str) -> None:
        self.activated = True
        self.state = "activated"


def test_ensure_orchestrator_activates_loaded():
    rt = _FakeRuntime("loaded")
    reconcile._ensure_orchestrator(rt)
    assert rt.activated is True


def test_ensure_orchestrator_skips_fault_and_missing():
    fault_rt = _FakeRuntime("fault")
    reconcile._ensure_orchestrator(fault_rt)
    assert fault_rt.activated is False
    missing_rt = _FakeRuntime("loaded")
    missing_rt.get_meta = lambda pid: None  # 磁盘无 orchestrator
    reconcile._ensure_orchestrator(missing_rt)
    assert missing_rt.activated is False


def test_resolve_agent_excludes_orchestrator():
    runtime = get_runtime()
    runtime.register_meta(_meta(ORCHESTRATOR_ID), "activated")
    runtime.register_meta(_meta("sub-agent"), "activated")
    assert runtime._resolve_agent("sub-agent").plugin_id == "sub-agent"
    assert runtime._resolve_agent(ORCHESTRATOR_ID) is None
    assert runtime._resolve_agent("no-such") is None


def test_tool_specs_for_orchestrator_includes_subagents():
    runtime = get_runtime()
    runtime.register_meta(_meta(ORCHESTRATOR_ID), "activated")
    runtime.register_meta(_meta("sub-agent"), "activated")
    specs = runtime.tool_specs_for(ORCHESTRATOR_ID)
    ids = {s["tool_id"] for s in specs}
    assert "sub-agent" in ids
    assert ORCHESTRATOR_ID not in ids
    sub = next(s for s in specs if s["tool_id"] == "sub-agent")
    assert "prompt" in sub["parameters_schema"]["properties"]


class _FakeGraph:
    def invoke(self, state, config=None):
        return {"messages": [{"role": "assistant", "content": "子答案"}]}


class _FakeAgent:
    system_prompt = "SYS"


def test_call_agent_returns_subagent_answer():
    runtime = get_runtime()
    pid = "sub-agent-2"
    meta = _meta(pid)
    runtime.register_meta(meta, "activated")
    runtime._instances[pid] = _FakeAgent()
    runtime._graphs[pid] = _FakeGraph()
    taskctx.set_current_task("orch-task")
    try:
        result = runtime._call_agent(meta, {"prompt": "hi"}, ORCHESTRATOR_ID)
    finally:
        taskctx.clear_current_task()
    assert result["ok"] is True
    assert result["data"] == "子答案"


def test_call_agent_rejects_inactive():
    runtime = get_runtime()
    pid = "sub-agent-3"
    meta = _meta(pid)
    runtime.register_meta(meta, "deactivated")
    runtime._instances[pid] = _FakeAgent()
    runtime._graphs[pid] = _FakeGraph()
    result = runtime._call_agent(meta, {"prompt": "hi"}, ORCHESTRATOR_ID)
    assert result["ok"] is False
    assert result["error_code"] == "TOOL_FORBIDDEN"


def _load_orchestrator_module():
    path = Path(__file__).resolve().parents[2] / "plugins" / "orchestrator-agent" / "main.py"
    spec = importlib.util.spec_from_file_location("orchestrator_plugin_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_orchestrator_extract_tool_calls_single_and_multi():
    mod = _load_orchestrator_module()
    single = '{"tool_calls": [{"tool_id": "personal-finance-agent", "args": {"prompt": "记账"}}]}'
    assert mod._extract_tool_calls(single) == [
        {"tool_id": "personal-finance-agent", "args": {"prompt": "记账"}},
    ]
    multi = ('{"tool_calls": ['
             '{"tool_id": "a", "args": {"prompt": "x"}},'
             '{"tool_id": "b", "args": {"prompt": "y"}}]}')
    assert [c["tool_id"] for c in mod._extract_tool_calls(multi)] == ["a", "b"]


def test_orchestrator_extract_tool_calls_wrapped_text_and_none():
    mod = _load_orchestrator_module()
    wrapped = '好的，我并行委派如下：\n{"tool_calls": [{"tool_id": "a", "args": {}}]}\n请稍候。'
    assert [c["tool_id"] for c in mod._extract_tool_calls(wrapped)] == ["a"]
    assert mod._extract_tool_calls("直接回答，无需工具。") is None
