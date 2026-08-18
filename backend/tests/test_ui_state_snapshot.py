"""M11 组件状态快照上报/查询/级联删除测试（v1.0 §5/§12.1）。"""
import pytest
from fastapi.testclient import TestClient

from nvwa_agent.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _make_task(client):
    conv_id = client.post("/api/v1/conversation/create",
                          json={"title": "快照测试"}).json()["conversation_id"]
    task_id = client.post("/api/v1/task/submit",
                          json={"conversation_id": conv_id, "prompt": "hi"}).json()["task_id"]
    return conv_id, task_id


def test_snapshot_report_and_query_ordered(client):
    conv_id, task_id = _make_task(client)

    resp = client.post(f"/api/v1/task/{task_id}/ui-state-snapshot", json={
        "event_seq": 2, "event_type": "agent:think",
        "states": [{"plugin_id": "demo-ui-think-visualizer",
                    "state": {"step": "thinking", "progress": 0.6}}],
    })
    assert resp.status_code == 200
    assert resp.json() == {"accepted": True, "snapshot_count": 1}

    resp = client.post(f"/api/v1/task/{task_id}/ui-state-snapshot", json={
        "event_seq": 1, "event_type": "task:start",
        "states": [{"plugin_id": "demo-ui-think-visualizer", "state": {"step": "start"}}],
    })
    assert resp.status_code == 200

    snapshots = client.get(
        f"/api/v1/task/{task_id}/ui-state-snapshots").json()["snapshots"]
    assert len(snapshots) == 2
    assert [s["event_seq"] for s in snapshots] == [1, 2]  # 按 event_seq 升序
    assert snapshots[0]["plugin_id"] == "demo-ui-think-visualizer"
    assert snapshots[0]["state"] == {"step": "start"}
    assert snapshots[1]["state"] == {"step": "thinking", "progress": 0.6}


def test_snapshot_report_task_not_found(client):
    resp = client.post("/api/v1/task/no-such-task/ui-state-snapshot", json={
        "event_seq": 1, "event_type": "task:start",
        "states": [{"plugin_id": "p", "state": {}}],
    })
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_snapshot_cascade_delete_on_conversation(client):
    """§5.5：删除会话 → task_record 级联删除 → ui_state_snapshot 级联删除。"""
    conv_id, task_id = _make_task(client)
    client.post(f"/api/v1/task/{task_id}/ui-state-snapshot", json={
        "event_seq": 1, "event_type": "task:start",
        "states": [{"plugin_id": "p", "state": {"a": 1}}],
    })
    assert client.get(
        f"/api/v1/task/{task_id}/ui-state-snapshots").json()["snapshots"]

    resp = client.delete(f"/api/v1/conversation/{conv_id}")
    assert resp.status_code == 200

    snapshots = client.get(
        f"/api/v1/task/{task_id}/ui-state-snapshots").json()["snapshots"]
    assert snapshots == []
