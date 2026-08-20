"""M16 端到端任务链路集成测试（mock 模式，v1.0 §10.2）。"""
import time

import pytest
from fastapi.testclient import TestClient

from nvwa_agent.app import create_app
from nvwa_agent.core.plugin_runtime import scan_and_reconcile
from nvwa_agent.core.plugin_runtime.runtime import get_runtime
from nvwa_agent.core.scheduler.queue import enqueue, start_worker


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_e2e_task_mock_flow(client):
    # 扫描 + 激活核心编排智能体（唯一任务入口）
    scan_and_reconcile(initial=False)
    get_runtime().activate("orchestrator-agent")

    conv_id = client.post("/api/v1/conversation/create",
                          json={"title": "e2e"}).json()["conversation_id"]
    task_id = client.post("/api/v1/task/submit",
                          json={"conversation_id": conv_id, "prompt": "你好"}).json()["task_id"]

    start_worker()
    enqueue(task_id)

    # 轮询等待任务完成（mock 模式无真实推理，很快完成）
    detail = {}
    for _ in range(50):
        detail = client.get(f"/api/v1/task/{task_id}").json()
        if detail["status"] in ("finish", "failed"):
            break
        time.sleep(0.2)

    assert detail["status"] == "finish", f"任务未成功完成：{detail}"
    assert detail["result"]

    # 验证事件链路：start -> think(分片) -> finish
    events = client.get(f"/api/v1/task/{task_id}/log").json()["events"]
    types = [e["event_type"] for e in events]
    assert "task:start" in types
    assert "agent:think" in types
    assert "task:finish" in types
