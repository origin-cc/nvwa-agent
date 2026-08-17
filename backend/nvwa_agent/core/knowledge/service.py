"""知识库服务（§12）：入库流水线（后台线程）/ 删除重建 / 检索。

状态机：parsing → indexing → ready / failed（KNOWLEDGE_PARSE_FAILED 记 error_msg）
"""
import threading
import uuid
from pathlib import Path

from nvwa_agent.config import get as get_config
from nvwa_agent.core.knowledge.embedding import EmbeddingUnavailable, get_embedding_service
from nvwa_agent.core.knowledge.parser import ParseError, chunk_text, extract_text
from nvwa_agent.core.knowledge.vector_store import get_vector_store
from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.paths import resolve_path
from nvwa_agent.database import session_scope
from nvwa_agent.models.knowledge import DocChunk, KnowledgeDoc

_log = get_core_logger()


class KnowledgeService:
    """知识库入库与检索门面（线程安全；入库为后台线程异步执行）。"""

    # ---------------- 入库 ----------------
    def create_doc(self, file_name: str, stored_path: str) -> str:
        doc_id = str(uuid.uuid4())
        with session_scope() as db:
            db.add(KnowledgeDoc(doc_id=doc_id, file_name=file_name,
                                file_path=stored_path, status="parsing"))
        threading.Thread(target=self._ingest, args=(doc_id,), daemon=True,
                         name=f"kb-ingest-{doc_id[:8]}").start()
        return doc_id

    def _ingest(self, doc_id: str) -> None:
        """后台流水线：解析→切片→向量化→写入FAISS→ready；任一步失败置failed。"""
        try:
            with session_scope() as db:
                doc = db.get(KnowledgeDoc, doc_id)
                file_path, file_name = doc.file_path, doc.file_name
            data_dir = resolve_path(get_config("data_dir", "./data"))
            text = extract_text(str(data_dir / file_path), Path(file_name).suffix)
            chunks = chunk_text(text)
            if not chunks:
                raise ParseError("文档内容为空或无法提取文本")

            self._set_status(doc_id, status="indexing")
            vectors = get_embedding_service().encode(chunks)
            index_ids = get_vector_store().add(vectors)

            with session_scope() as db:
                for i, (content, fid) in enumerate(zip(chunks, index_ids)):
                    db.add(DocChunk(chunk_id=str(uuid.uuid4()), doc_id=doc_id,
                                    chunk_index=i, content=content, faiss_index_id=fid))
                db.get(KnowledgeDoc, doc_id).chunk_count = len(chunks)
            self._set_status(doc_id, status="ready")
            _log.info("知识库文档入库完成 doc=%s chunks=%d", doc_id, len(chunks))
        except (ParseError, EmbeddingUnavailable) as exc:
            self._set_status(doc_id, status="failed", error_msg=str(exc))
            _log.warning("知识库入库失败 doc=%s: %s", doc_id, exc)
        except Exception as exc:
            self._set_status(doc_id, status="failed", error_msg=f"入库内部错误：{exc}")
            _log.exception("知识库入库异常 doc=%s", doc_id)

    @staticmethod
    def _set_status(doc_id: str, *, status: str, error_msg: str | None = None) -> None:
        with session_scope() as db:
            doc = db.get(KnowledgeDoc, doc_id)
            if doc is None:
                return
            doc.status = status
            doc.error_msg = error_msg

    # ---------------- 删除（重建索引 §12.3） ----------------
    def delete_doc(self, doc_id: str) -> bool:
        with session_scope() as db:
            doc = db.get(KnowledgeDoc, doc_id)
            if doc is None:
                return False
            db.query(DocChunk).filter(DocChunk.doc_id == doc_id).delete()
            db.delete(doc)
        self.rebuild_index()
        return True

    def rebuild_index(self) -> int:
        """从 doc_chunk 全量重建 FAISS 索引（删除文档后 / 启动对账）。"""
        with session_scope() as db:
            chunks = db.query(DocChunk).filter(DocChunk.faiss_index_id.isnot(None)) \
                .order_by(DocChunk.created_at, DocChunk.chunk_id).all()
            if not chunks:
                import numpy as np
                get_vector_store().rebuild(np.zeros((0, 1), dtype="float32"))
                return 0
            contents = [c.content for c in chunks]
        try:
            vectors = get_embedding_service().encode(contents)
        except EmbeddingUnavailable as exc:
            _log.warning("索引重建跳过（Embedding 不可用）: %s", exc)
            return 0
        index_ids = get_vector_store().rebuild(vectors)
        with session_scope() as db:
            for chunk, fid in zip(chunks, index_ids):
                row = db.get(DocChunk, chunk.chunk_id)
                if row is not None:
                    row.faiss_index_id = fid
        _log.info("FAISS 索引重建完成：%d 向量", len(index_ids))
        return len(index_ids)

    def reconcile_on_boot(self) -> None:
        """启动对账：doc_chunk 数量与索引总量不一致时重建（索引文件丢失/换模型）。"""
        try:
            with session_scope() as db:
                chunk_count = db.query(DocChunk).count()
            if chunk_count != get_vector_store().total:
                _log.info("知识库对账：chunk=%d index=%d，触发重建", chunk_count, get_vector_store().total)
                self.rebuild_index()
        except Exception:
            _log.exception("知识库启动对账失败")

    # ---------------- 检索（§12.4） ----------------
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """FAISS检索 → faiss_index_id → chunk_id → 原文+文档元信息。"""
        if not query.strip():
            return []
        query_vec = get_embedding_service().encode_query(query)
        hits = get_vector_store().search(query_vec, top_k=top_k)
        if not hits:
            return []
        id_map = {fid: (score) for fid, score in hits}
        with session_scope() as db:
            rows = db.query(DocChunk).filter(DocChunk.faiss_index_id.in_(list(id_map))).all()
            results = []
            for row in rows:
                doc = db.get(KnowledgeDoc, row.doc_id)
                results.append({
                    "chunk_id": row.chunk_id,
                    "doc_id": row.doc_id,
                    "file_name": doc.file_name if doc else "",
                    "chunk_index": row.chunk_index,
                    "content": row.content,
                    "score": round(id_map.get(row.faiss_index_id, 0.0), 4),
                })
            results.sort(key=lambda r: r["score"], reverse=True)
            return results


_service: KnowledgeService | None = None
_service_lock = threading.Lock()


def get_knowledge_service() -> KnowledgeService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = KnowledgeService()
    return _service
