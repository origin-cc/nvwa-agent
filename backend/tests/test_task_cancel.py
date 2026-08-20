"""任务取消能力测试（§10 停止按钮）：cancel 端点 + queue 取消信号。"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from nvwa_agent.app import create_app
from nvwa_agent.core.scheduler import queue as queue_mod
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import Conversation, SessionEventLog, TaskRecord


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _submit(client) -> str:
    conv_id = client.post("/api/v1/conversation/create",
                          json={"title": "取消测试"}).json()["conversation_id"]
    return client.post("/api/v1/task/submit",
                       json={"conversation_id": conv_id, "prompt": "hi"}).json()["task_id"]


def test_cancel_task_not_found(client):
    resp = client.post("/api/v1/task/no-such-task/cancel")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "NOT_FOUND"
    assert "message" in body


def test_cancel_task_ok(client):
    task_id = _submit(client)
    resp = client.post(f"/api/v1/task/{task_id}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"task_id": task_id, "status": "cancelling"}


def test_cancel_signal_roundtrip():
    task_id = str(uuid.uuid4())
    assert queue_mod.is_cancelled(task_id) is False
    queue_mod.cancel_task(task_id)
    assert queue_mod.is_cancelled(task_id) is True
    queue_mod._clear_cancel(task_id)
    assert queue_mod.is_cancelled(task_id) is False


def test_run_task_skips_cancelled_pending():
    conv_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    with session_scope() as db:
        db.add(Conversation(conversation_id=conv_id, title="取消"))
        db.add(TaskRecord(
            task_id=task_id, conversation_id=conv_id,
            status="pending", input_prompt="hi", file_ids=json.dumps([]),
        ))
    queue_mod.cancel_task(task_id)
    queue_mod._run_task(task_id)

    with session_scope() as db:
        row = db.get(TaskRecord, task_id)
        assert row.status == "cancelled"
        assert row.finished_at is not None

    with session_scope() as db:
        evts = (db.query(SessionEventLog)
                  .filter(SessionEventLog.task_id == task_id).all())
    assert any(e.event_type == "task:cancelled" for e in evts)
