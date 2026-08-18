"""ApiLlmClient（OpenAI 兼容 / DeepSeek）单元测试：全部走 httpx.MockTransport，无真实网络。"""
import json

import httpx
import pytest

from nvwa_agent.core.llm import LlmProviderError
from nvwa_agent.core.llm.api_client import ApiLlmClient

_BASE = {"base_url": "https://api.example.com", "api_key": "sk-test", "model": "test-model"}


def _patch_client(monkeypatch, handler):
    """将 api_client 内部的 httpx.Client 替换为携带 MockTransport 的工厂。"""
    real_client = httpx.Client

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("nvwa_agent.core.llm.api_client.httpx.Client", factory)


def test_init_requires_full_config():
    with pytest.raises(LlmProviderError):
        ApiLlmClient(base_url="", api_key="k", model="m")
    with pytest.raises(LlmProviderError):
        ApiLlmClient(base_url="u", api_key="", model="m")
    with pytest.raises(LlmProviderError):
        ApiLlmClient(base_url="u", api_key="k", model="")


def test_chat_once_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is False
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "完整回答"}}],
        })

    _patch_client(monkeypatch, handler)
    client = ApiLlmClient(**_BASE)
    assert client.chat([{"role": "user", "content": "hi"}], stream=False) == "完整回答"


def test_chat_once_http_error(monkeypatch):
    def handler(request):
        return httpx.Response(401, text='{"error": "bad key"}')

    _patch_client(monkeypatch, handler)
    client = ApiLlmClient(**_BASE)
    with pytest.raises(LlmProviderError, match="HTTP 401"):
        client.chat([{"role": "user", "content": "hi"}], stream=False)


def test_chat_once_malformed_body(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"unexpected": True})

    _patch_client(monkeypatch, handler)
    client = ApiLlmClient(**_BASE)
    with pytest.raises(LlmProviderError, match="结构异常"):
        client.chat([{"role": "user", "content": "hi"}], stream=False)


def test_chat_stream_yields_shards(monkeypatch):
    sse = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n'
        "\n"
        'data: {"choices":[{"delta":{"content":"好"}}]}\n'
        'data: {"choices":[{"delta":{}}]}\n'          # 空 delta 跳过
        'data: {"choices":[]}\n'                       # 空 choices 跳过
        "data: [DONE]\n"
        'data: {"choices":[{"delta":{"content":"忽略"}}]}\n'  # DONE 后忽略
    )

    def handler(request):
        return httpx.Response(200, text=sse, headers={"Content-Type": "text/event-stream"})

    _patch_client(monkeypatch, handler)
    client = ApiLlmClient(**_BASE)
    shards = list(client.chat([{"role": "user", "content": "hi"}], stream=True))
    assert shards == ["你", "好"]


def test_chat_stream_http_error(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="server boom")

    _patch_client(monkeypatch, handler)
    client = ApiLlmClient(**_BASE)
    gen = client.chat([{"role": "user", "content": "hi"}], stream=True)
    with pytest.raises(LlmProviderError, match="HTTP 500"):
        next(gen)
