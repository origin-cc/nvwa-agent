"""快照核心 apply_snapshot（§7.4/§11 场景3）单元测试：使用 FakeRuntime 隔离。"""
from nvwa_agent.core import snapshot as snapshot_mod


class FakeRuntime:
    def __init__(self, plugins: dict[str, str]):
        self._plugins = dict(plugins)  # pid -> state

    def list_plugins(self):
        return [{"plugin_id": pid, "state": st, "type": "backend_agent",
                 "plugin_config": {}} for pid, st in self._plugins.items()]

    def get_state(self, pid):
        return self._plugins.get(pid)

    def activate(self, pid):
        self._plugins[pid] = "activated"

    def deactivate(self, pid):
        self._plugins[pid] = "deactivated"


def _snapshot(entries: dict) -> dict:
    plugins = {"backend_agents": [], "backend_tools": [], "ui_plugins": []}
    for pid, enabled in entries.items():
        plugins["backend_agents"].append({"plugin_id": pid, "enabled": enabled, "config": {}})
    return {"snapshot_meta": {"name": "t"}, "plugins": plugins}


def test_apply_activates_and_deactivates(monkeypatch):
    rt = FakeRuntime({"a": "deactivated", "b": "activated"})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(_snapshot({"a": True, "b": False}))
    assert result["applied"] == ["a"]
    assert result["deactivated"] == ["b"]
    assert result["missing_plugin_ids"] == []
    assert rt.get_state("a") == "activated"
    assert rt.get_state("b") == "deactivated"


def test_apply_missing_plugin_warns_not_blocks(monkeypatch):
    """§11 场景3：缺失插件告警跳过，其余插件正常应用。"""
    rt = FakeRuntime({"a": "deactivated"})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(_snapshot({"a": True, "ghost": True}))
    assert result["applied"] == ["a"]
    assert result["missing_plugin_ids"] == ["ghost"]
    assert any("ghost" in w for w in result["warnings"])


def test_apply_full_overwrite_deactivates_unlisted(monkeypatch):
    """PRD 3.5.2 全量覆盖：不在快照内的已激活插件一律禁用。"""
    rt = FakeRuntime({"a": "activated", "b": "activated"})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(_snapshot({"a": True}))
    assert result["deactivated"] == ["b"]
    assert rt.get_state("b") == "deactivated"


def test_apply_noop_when_state_matches(monkeypatch):
    rt = FakeRuntime({"a": "activated"})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(_snapshot({"a": True}))
    assert result["applied"] == []   # 已激活，无需迁移
    assert result["deactivated"] == []


def test_apply_empty_snapshot_deactivates_all(monkeypatch):
    rt = FakeRuntime({"a": "activated", "b": "activated"})
    monkeypatch.setattr(snapshot_mod, "get_runtime", lambda: rt)
    result = snapshot_mod.apply_snapshot(_snapshot({}))
    assert sorted(result["deactivated"]) == ["a", "b"]
