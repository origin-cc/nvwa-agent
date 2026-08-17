"""FAISS 索引管理（§12.1-12.4）：向量位置 ↔ doc_chunk.faiss_index_id 一一映射。

- IndexFlatIP + 归一化向量 = 余弦相似度检索
- v0.1-alpha 删除采用全量重建（§12.3 妥协方案）
- 持久化：data/faiss_index/index.faiss；映射权威数据在 doc_chunk 表
"""
import threading
from pathlib import Path

import numpy as np

from nvwa_agent.config import get as get_config
from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.paths import resolve_path

_log = get_core_logger()


class VectorStore:
    """进程内 FAISS 索引单例（线程安全）。"""

    def __init__(self) -> None:
        self._index = None
        self._dim: int | None = None
        self._lock = threading.RLock()

    # ---------------- 路径 ----------------
    def _index_dir(self) -> Path:
        directory = resolve_path(get_config("data_dir", "./data")) / "faiss_index"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _index_file(self) -> Path:
        return self._index_dir() / "index.faiss"

    # ---------------- 索引生命周期 ----------------
    def _ensure_index(self, dim: int):
        """懒创建/加载与维度一致的空索引或磁盘索引。"""
        import faiss

        with self._lock:
            if self._index is not None and self._dim == dim:
                return self._index
            file = self._index_file()
            if file.is_file():
                index = faiss.read_index(str(file))
                if index.d != dim:  # 维度变化（换模型）：作废旧索引，调用方重建
                    _log.warning("FAISS 索引维度 %d 与模型 %d 不一致，丢弃旧索引", index.d, dim)
                    index = faiss.IndexFlatIP(dim)
            else:
                index = faiss.IndexFlatIP(dim)
            self._index = index
            self._dim = dim
            return index

    def add(self, vectors: np.ndarray) -> list[int]:
        """写入向量，返回对应的 faiss_index_id 列表（连续分配）。"""
        if len(vectors) == 0:
            return []
        index = self._ensure_index(int(vectors.shape[1]))
        with self._lock:
            start = index.ntotal
            index.add(vectors)
            self._persist()
            return list(range(start, start + len(vectors)))

    def search(self, query: np.ndarray, top_k: int = 5) -> list[tuple[int, float]]:
        """检索：返回 [(faiss_index_id, score)]，按相似度降序。"""
        index = self._ensure_index(int(query.shape[0]))
        with self._lock:
            if index.ntotal == 0:
                return []
            k = min(top_k, index.ntotal)
            scores, ids = index.search(query.reshape(1, -1).astype("float32"), k)
            return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    def rebuild(self, vectors: np.ndarray) -> list[int]:
        """清空并全量重建（删除文档后调用，§12.3）；空向量集仅清空索引。"""
        with self._lock:
            self._index = None
            self._dim = None
            self._index_file().unlink(missing_ok=True)
        if len(vectors) == 0:
            return []
        return self.add(vectors)

    @property
    def total(self) -> int:
        with self._lock:
            return int(self._index.ntotal) if self._index is not None else 0

    def _persist(self) -> None:
        import faiss

        try:
            faiss.write_index(self._index, str(self._index_file()))
        except Exception:
            _log.exception("FAISS 索引持久化失败")


_store: VectorStore | None = None
_store_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = VectorStore()
    return _store
