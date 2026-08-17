"""知识库 API（§9 文件与知识库）：upload 异步入库 / list 轮询 / delete 重建。"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import select

from nvwa_agent.config import get as get_config
from nvwa_agent.core.knowledge import get_knowledge_service
from nvwa_agent.core.knowledge.parser import SUPPORTED_SUFFIXES
from nvwa_agent.core.paths import resolve_path
from nvwa_agent.database import get_db, session_scope
from nvwa_agent.models.knowledge import KnowledgeDoc
from nvwa_agent.server.errors import ApiError

router = APIRouter()


@router.post("/api/v1/knowledge/upload")
async def upload_document(file: UploadFile):
    limit_mb = int(get_config("upload_max_file_size_mb", 100))
    data = await file.read()
    if len(data) > limit_mb * 1024 * 1024:
        raise ApiError("FILE_TOO_LARGE", f"文件超过单文件大小上限 {limit_mb}MB")

    original_name = file.filename or "unnamed"
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ApiError("VALIDATION_ERROR",
                       f"不支持的文件类型 {suffix or '(无扩展名)'}，仅支持 {sorted(SUPPORTED_SUFFIXES)}")

    file_uuid = str(uuid.uuid4())
    stored_name = f"{file_uuid}{suffix}"
    kb_dir = resolve_path(get_config("data_dir", "./data")) / "uploads" / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / stored_name).write_bytes(data)

    doc_id = get_knowledge_service().create_doc(original_name, f"uploads/kb/{stored_name}")
    return {"doc_id": doc_id, "status": "parsing"}


@router.get("/api/v1/knowledge/list")
def list_documents(db=Depends(get_db)):
    rows = db.execute(
        select(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc())
    ).scalars().all()
    docs = [
        {
            "doc_id": r.doc_id,
            "file_name": r.file_name,
            "status": r.status,
            "chunk_count": r.chunk_count,
            "error_msg": r.error_msg,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"docs": docs}


@router.delete("/api/v1/knowledge/{doc_id}")
def delete_document(doc_id: str):
    if not get_knowledge_service().delete_doc(doc_id):
        raise ApiError("NOT_FOUND", f"知识库文档 {doc_id} 不存在")
    return {"deleted": doc_id}
