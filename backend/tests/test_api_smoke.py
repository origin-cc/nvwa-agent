"""REST API 契约冒烟测试（§18）：FastAPI TestClient，不进入 lifespan。

- 不启动任务 Worker / 插件自动恢复 / Embedding（lifespan 才做），任务保持 pending；
- 插件扫描走真实 plugins/ 目录（只读 + 内存加载，写库均落在测试临时库）。
"""
import pytest
from fastapi.testclient import TestClient

from nvwa_agent.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_conversation_create_and_list(client):
    resp = client.post("/api/v1/conversation/create", json={"title": "测试会话"})
    assert resp.status_code == 200
    conv_id = resp.json()["conversation_id"]

    resp = client.get("/api/v1/conversation/list")
    assert resp.status_code == 200
    assert any(c["conversation_id"] == conv_id for c in resp.json()["conversations"])


def test_task_submit_pending_and_detail(client):
    conv_id = client.post("/api/v1/conversation/create",
                          json={"title": "任务测试"}).json()["conversation_id"]
    resp = client.post("/api/v1/task/submit",
                       json={"conversation_id": conv_id, "prompt": "你好"})
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    assert resp.json()["status"] == "pending"

    detail = client.get(f"/api/v1/task/{task_id}").json()
    assert detail["task_id"] == task_id
    assert detail["status"] == "pending"  # Worker 未启动（无 lifespan）


def test_task_not_found_error_format(client):
    resp = client.get("/api/v1/task/no-such-task")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "NOT_FOUND"
    assert "message" in body


def test_task_submit_validation_and_not_found(client):
    # 空 prompt -> 400 VALIDATION_ERROR
    resp = client.post("/api/v1/task/submit", json={"prompt": "  "})
    assert resp.status_code == 400
    assert resp.json()["code"] == "VALIDATION_ERROR"
    # 不存在的会话 -> 404
    resp = client.post("/api/v1/task/submit",
                       json={"conversation_id": "no-such-conv", "prompt": "hi"})
    assert resp.status_code == 404
    # 缺省 conversation_id 自动创建新会话（设计行为）
    resp = client.post("/api/v1/task/submit", json={"prompt": "自动建会话"})
    assert resp.status_code == 200
    assert resp.json()["conversation_id"]


def test_plugins_scan_and_list(client):
    resp = client.post("/api/v1/plugins/scan")
    assert resp.status_code == 200

    resp = client.get("/api/v1/plugins/list")
    assert resp.status_code == 200
    plugins = resp.json()["plugins"]
    ids = {p["plugin_id"] for p in plugins}
    assert "demo-agent-plugin" in ids
    assert "demo-file-tool" in ids


def test_plugin_activate_and_deactivate(client):
    client.post("/api/v1/plugins/scan")
    resp = client.post("/api/v1/plugins/demo-agent-plugin/activate")
    assert resp.status_code == 200

    state = {p["plugin_id"]: p["state"] for p in
             client.get("/api/v1/plugins/list").json()["plugins"]}
    assert state["demo-agent-plugin"] == "activated"

    resp = client.post("/api/v1/plugins/demo-agent-plugin/deactivate")
    assert resp.status_code == 200


def test_plugin_not_found(client):
    resp = client.post("/api/v1/plugins/no-such-plugin/activate")
    assert resp.status_code in (400, 404)
    assert resp.json()["code"]


def test_system_config_get_and_put(client):
    resp = client.get("/api/v1/system/config")
    assert resp.status_code == 200
    assert "configs" in resp.json()

    resp = client.put("/api/v1/system/config",
                      json={"configs": {"model_temperature": 0.5}})
    assert resp.status_code == 200
    value = [c["value"] for c in
             client.get("/api/v1/system/config").json()["configs"]
             if c["key"] == "model_temperature"][0]
    assert value == 0.5


def test_snapshot_save_list_load_delete(client):
    client.post("/api/v1/plugins/scan")
    client.post("/api/v1/plugins/demo-agent-plugin/activate")

    resp = client.post("/api/v1/snapshot/save", json={"name": "测试快照"})
    assert resp.status_code == 200
    snap_id = resp.json()["snapshot_id"]

    listed = client.get("/api/v1/snapshot/list").json()["snapshots"]
    assert any(s["snapshot_id"] == snap_id for s in listed)

    # 禁用后加载快照应恢复激活状态
    client.post("/api/v1/plugins/demo-agent-plugin/deactivate")
    resp = client.post(f"/api/v1/snapshot/{snap_id}/load")
    assert resp.status_code == 200
    assert "demo-agent-plugin" in resp.json()["applied"]

    resp = client.delete(f"/api/v1/snapshot/{snap_id}")
    assert resp.status_code == 200
    listed = client.get("/api/v1/snapshot/list").json()["snapshots"]
    assert not any(s["snapshot_id"] == snap_id for s in listed)


def test_snapshot_load_not_found(client):
    resp = client.post("/api/v1/snapshot/999999/load")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_task_log_after_submit(client):
    conv_id = client.post("/api/v1/conversation/create",
                          json={"title": "日志测试"}).json()["conversation_id"]
    task_id = client.post("/api/v1/task/submit",
                          json={"conversation_id": conv_id, "prompt": "hi"}).json()["task_id"]
    resp = client.get(f"/api/v1/task/{task_id}/log")
    assert resp.status_code == 200
    assert "events" in resp.json()
