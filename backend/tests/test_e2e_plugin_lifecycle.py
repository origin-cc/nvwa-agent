"""M16 插件生命周期集成测试（v1.0 §10.2：扫描→激活→禁用→卸载→联动）。"""
import pytest
from fastapi.testclient import TestClient

from nvwa_agent.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _states(client):
    return {p["plugin_id"]: p["state"]
            for p in client.get("/api/v1/plugins/list").json()["plugins"]}


def test_plugin_lifecycle_scan_activate_deactivate_unload(client):
    client.post("/api/v1/plugins/scan")

    # 激活 + 前端联动（bind_ui_plugin_id）
    resp = client.post("/api/v1/plugins/demo-agent-plugin/activate")
    assert resp.status_code == 200
    states = _states(client)
    assert states["demo-agent-plugin"] == "activated"
    assert states.get("demo-ui-think-visualizer") == "activated"  # 联动激活

    # 禁用
    client.post("/api/v1/plugins/demo-agent-plugin/deactivate")
    states = _states(client)
    assert states["demo-agent-plugin"] == "deactivated"

    # 卸载
    client.post("/api/v1/plugins/demo-agent-plugin/unload")
    states = _states(client)
    assert states["demo-agent-plugin"] == "unloaded"

    # 重新激活（unloaded -> loaded -> activated）
    client.post("/api/v1/plugins/demo-agent-plugin/activate")
    states = _states(client)
    assert states["demo-agent-plugin"] == "activated"


def test_activate_dependency_cascade_and_friendly_error(client):
    """依赖未激活：非连带返回友好错误（不标 fault）；cascade=true 连带激活依赖。"""
    client.post("/api/v1/plugins/scan")

    # 非连带激活：依赖未激活 → 409 友好错误，插件不进入 fault
    resp = client.post("/api/v1/plugins/personal-finance-agent/activate")
    assert resp.status_code == 409
    assert resp.json()["code"] == "PLUGIN_DEPENDENCY_NOT_ACTIVATED"
    states = _states(client)
    assert states["finance-ledger-tool"] == "loaded"
    assert states["personal-finance-agent"] != "fault"

    # 连带激活：cascade=true → 先激活依赖工具，再激活 Agent
    resp = client.post("/api/v1/plugins/personal-finance-agent/activate?cascade=true")
    assert resp.status_code == 200
    states = _states(client)
    assert states["finance-ledger-tool"] == "activated"
    assert states["personal-finance-agent"] == "activated"
