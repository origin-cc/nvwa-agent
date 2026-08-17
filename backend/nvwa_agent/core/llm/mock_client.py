"""模拟推理客户端（§10 模拟调试模式）：不请求真实模型，返回带 [MOCK] 标记的应答。"""
from typing import Iterator


class MockLlmClient:
    """mock 模式客户端：流式分片迭代器 + 非流式完整字符串。"""

    def __init__(self, params: dict | None = None) -> None:
        self.params = params or {}

    def chat(self, messages: list[dict], stream: bool = True) -> Iterator[str] | str:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content", ""))[:120]
                break
        content = (
            f"[MOCK] 模拟应答（mock_mode）：已收到输入「{user_text}」。"
            "当前为模拟模型调试模式，未调用真实大模型推理。"
        )
        if not stream:
            return content

        def _iter() -> Iterator[str]:
            step = 12  # 每分片12字符，模拟打字机流式输出
            for i in range(0, len(content), step):
                yield content[i:i + step]

        return _iter()
