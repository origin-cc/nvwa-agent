"""M15 OpenAPI 文档测试（v1.0 §9：openapi.json / Swagger / Redoc）。"""
import pytest
from fastapi.testclient import TestClient

from nvwa_agent.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_openapi_json_contains_paths(client):
    resp = client.get("/api/v1/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert "paths" in spec
    assert "/api/v1/audit/events" in spec["paths"]
    assert "/api/v1/task/{task_id}/ui-state-snapshot" in spec["paths"]
    assert "/api/v1/plugins/{plugin_id}/logs" in spec["paths"]


def test_swagger_and_redoc_accessible(client):
    assert client.get("/api/v1/docs").status_code == 200
    assert client.get("/api/v1/redoc").status_code == 200
