"""OpenAI 兼容 API 推理客户端（§10）：DeepSeek 等，基于 httpx 直连。

- 流式：SSE data: 行解析 delta.content 分片 yield（由 LlmServiceImpl 转 agent:think）
- 非流式：返回完整字符串（意图识别等内部调用）
- 任何网络/协议错误统一抛 LlmProviderError（调度器转 LLM_INFER_FAILED，§11 场景4）
"""
import json
from typing import Iterator

import httpx

from nvwa_agent.core.llm import LlmProviderError

_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)


class ApiLlmClient:
    """OpenAI 兼容 /chat/completions 客户端。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 params: dict | None = None) -> None:
        if not base_url or not api_key or not model:
            raise LlmProviderError(
                "api 推理配置不完整：请在系统配置中设置 api_base_url / api_key / api_model")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"}
        self._model = model
        self._params = params or {}

    def _body(self, messages: list[dict], stream: bool) -> dict:
        body = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "temperature": self._params.get("temperature", 0.7),
            "max_tokens": int(self._params.get("max_tokens", 2048)),
            "top_p": self._params.get("top_p", 1.0),
        }
        stop = self._params.get("stop_sequences") or []
        if stop:
            body["stop"] = stop
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    @staticmethod
    def _raise_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            snippet = resp.text[:300]
            raise LlmProviderError(
                f"API 推理请求失败 HTTP {resp.status_code}: {snippet}")

    def chat(self, messages: list[dict], stream: bool = True) -> Iterator[str] | str:
        if not stream:
            return self._chat_once(messages)
        return self._chat_stream(messages)

    def _chat_once(self, messages: list[dict]) -> str:
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(self._url, headers=self._headers,
                                   json=self._body(messages, stream=False))
                self._raise_status(resp)
                data = resp.json()
        except LlmProviderError:
            raise
        except httpx.HTTPError as exc:
            raise LlmProviderError(f"API 推理网络异常: {exc}") from exc
        except ValueError as exc:
            raise LlmProviderError(f"API 响应非JSON: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmProviderError(
                f"API 响应结构异常: {json.dumps(data, ensure_ascii=False)[:300]}") from exc

    def _chat_stream(self, messages: list[dict]) -> Iterator[str]:
        def _iter() -> Iterator[str]:
            try:
                with httpx.Client(timeout=_TIMEOUT) as client:
                    with client.stream("POST", self._url, headers=self._headers,
                                       json=self._body(messages, stream=True)) as resp:
                        self._raise_status(resp)
                        for line in resp.iter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                return
                            try:
                                chunk = json.loads(payload)
                            except ValueError:
                                continue
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            piece = (choices[0].get("delta") or {}).get("content")
                            if piece:
                                yield piece
            except LlmProviderError:
                raise
            except httpx.HTTPError as exc:
                raise LlmProviderError(f"API 流式推理网络异常: {exc}") from exc

        return _iter()
