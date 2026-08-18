"""M14 快照导入完善测试（v1.0 §8：fault 跳过 / config 回退 / 缺失跳过）。"""
from types import SimpleNamespace

from nvwa_agent.core import snapshot as snapshot_mod


class FakeRuntime:
    def __init__(self, plugins, metas=None):
        self._plugins = dict(plugins)  # pid -> state
        self._metas = metas or {}

    def list_plugins(self):
        return [{"plugin_id": pid, "state": st, "type": "backend_agent",
                 "plugin_config": {}} for pid, st in self._plugins.items()]

    def get_state(self, pid):
        return self._plugins.get(pid)

    def get_meta(self, pid):
        return self._metas.get(pid)

    def activate(self, pid):
        self._plugins[pid] = "activated"

    def deactivate(self, pid):
        self._plugins[pid] = "deactivated"


def _snapshot(entries):
    plugins = {"backend_agents": [], "backend_tools": [], "ui_plugins": []}
    for pid, spec in entries.items():
        plugins["backend_agents"].append({
            "plugin_id": pid,
            "enabled": spec.get("enabled", True),
            "config": spec.get("config", {}),
        })
    return {"snapshot_meta": {"name": "t"}, "plugins": plugins}


def test_import_skips_fault_plugin(monkeypatch):
    rt = FakeRuntime({"a": "deactivated", "bad": "fault"})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(
        _snapshot({"a": {"enabled": True}, "bad": {"enabled": True}}))
    assert result["applied"] == ["a"]
    assert result["invalid_plugin_ids"] == ["bad"]
    assert any("bad" in w for w in result["warnings"])


def test_import_config_type_mismatch_rollback(monkeypatch):
    meta = SimpleNamespace(config={"temperature": 0.7})
    rt = FakeRuntime({"a": "deactivated"}, metas={"a": meta})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(
        _snapshot({"a": {"enabled": True, "config": {"temperature": "hot"}}}))
    assert result["applied"] == ["a"]
    assert any("temperature" in w for w in result["warnings"])


def test_import_missing_plugin_skips(monkeypatch):
    rt = FakeRuntime({"a": "deactivated"})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(
        _snapshot({"a": {"enabled": True}, "ghost": {"enabled": True}}))
    assert result["missing_plugin_ids"] == ["ghost"]
    assert result["applied"] == ["a"]
