"""M13 审计查询 API 测试（v1.0 §7：过滤/分页/悬空 task_id）。"""
import json

import pytest
from fastapi.testclient import TestClient

from nvwa_agent.app import create_app
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import SessionEventLog


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _insert_event(task_id, event_type, payload):
    with session_scope() as db:
        db.add(SessionEventLog(
            task_id=task_id, event_type=event_type,
            event_payload=json.dumps(payload, ensure_ascii=False),
        ))


def test_audit_filter_by_task_and_type(client):
    _insert_event("task-a", "tool:error", {"tool_id": "t1", "error_msg": "x"})
    _insert_event("task-a", "agent:think", {"agent_id": "a1", "seq": 1})
    _insert_event("task-b", "tool:call", {"tool_id": "t2", "call_args": {}})

    resp = client.get("/api/v1/audit/events?task_id=task-a")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    resp = client.get("/api/v1/audit/events?task_id=task-a&event_type=tool:error")
    assert resp.json()["total"] == 1
    assert resp.json()["events"][0]["event_type"] == "tool:error"


def test_audit_filter_by_plugin_id(client):
    _insert_event("task-c", "tool:call", {"tool_id": "my-tool", "call_args": {}})
    _insert_event("task-c", "agent:think", {"agent_id": "my-agent", "seq": 1})
    _insert_event("task-c", "plugin:error", {"plugin_id": "my-plugin", "error_code": "X"})

    assert client.get("/api/v1/audit/events?plugin_id=my-tool").json()["total"] == 1
    assert client.get("/api/v1/audit/events?plugin_id=my-agent").json()["total"] == 1
    assert client.get("/api/v1/audit/events?plugin_id=my-plugin").json()["total"] == 1


def test_audit_pagination(client):
    for i in range(5):
        _insert_event("task-page", "agent:think", {"seq": i})
    body = client.get("/api/v1/audit/events?task_id=task-page&page=1&page_size=2").json()
    assert body["total"] == 5
    assert len(body["events"]) == 2


def test_audit_dangling_task_id(client):
    """悬空 task_id（无 task_record）：事件仍可查询（§7.3）。"""
    _insert_event("ghost-task", "task:start", {})
    assert client.get("/api/v1/audit/events?task_id=ghost-task").json()["total"] == 1
