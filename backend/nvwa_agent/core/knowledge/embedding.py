"""Embedding 服务（§12.5）：sentence-transformers 懒加载，与 vLLM 推理解耦。

- 模型路径由 system_config.embedding_model_path 配置（支持 HF 标识符自动下载）
- 路径为空或加载失败抛 EmbeddingUnavailable：知识库入库置 failed，不影响任务对话链路
"""
import threading

import numpy as np

from nvwa_agent.config import get as get_config
from nvwa_agent.core.log import get_core_logger

_log = get_core_logger()


class EmbeddingUnavailable(Exception):
    """Embedding 模型未配置或加载失败。"""


class EmbeddingService:
    """sentence-transformers 懒加载单例服务（线程安全）。"""

    def __init__(self) -> None:
        self._model = None
        self._model_path: str | None = None
        self._lock = threading.Lock()
        self._failed_path: str | None = None  # 已失败路径缓存，避免反复重试大模型加载

    def _ensure_model(self):
        path = str(get_config("embedding_model_path", "") or "").strip()
        if not path:
            raise EmbeddingUnavailable(
                "embedding_model_path 未配置：请在系统配置中填写 sentence-transformers 模型路径")
        if self._model is not None and path == self._model_path:
            return self._model
        with self._lock:
            if self._model is not None and path == self._model_path:
                return self._model
            if path == self._failed_path:
                raise EmbeddingUnavailable(f"Embedding 模型此前加载失败（{path}），已缓存失败结果")
            try:
                from sentence_transformers import SentenceTransformer
                _log.info("加载 Embedding 模型: %s", path)
                model = SentenceTransformer(path)
            except Exception as exc:  # 模型路径错误/下载失败/依赖缺失
                self._failed_path = path
                _log.error("Embedding 模型加载失败: %s", exc)
                raise EmbeddingUnavailable(
                    f"Embedding 模型加载失败（{path}）：{exc}") from exc
            self._model = model
            self._model_path = path
            self._failed_path = None
            _log.info("Embedding 模型就绪: %s dim=%d", path, self._dim_of(model))
            return model

    @staticmethod
    def _dim_of(model) -> int:
        get_dim = getattr(model, "get_embedding_dimension", None) \
            or model.get_sentence_embedding_dimension
        return int(get_dim())

    @property
    def dimension(self) -> int:
        return self._dim_of(self._ensure_model())

    def encode(self, texts: list[str]) -> np.ndarray:
        """文本批量向量化，返回 L2 归一化矩阵（n, dim），供余弦相似检索。"""
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype="float32")

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


_service: EmbeddingService | None = None
_service_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = EmbeddingService()
    return _service
