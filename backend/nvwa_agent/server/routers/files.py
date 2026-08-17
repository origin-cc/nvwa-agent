"""文件上传 API（§9 文件上传）：upload/delete + 大小上限校验。"""
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile

from nvwa_agent.config import get as get_config
from nvwa_agent.core.paths import resolve_path
from nvwa_agent.database import session_scope
from nvwa_agent.models.misc import UploadedFile
from nvwa_agent.server.errors import ApiError

router = APIRouter()


@router.post("/api/v1/files/upload")
async def upload_file(file: UploadFile):
    limit_mb = int(get_config("upload_max_file_size_mb", 100))
    data = await file.read()
    if len(data) > limit_mb * 1024 * 1024:
        raise ApiError("FILE_TOO_LARGE", f"文件超过单文件大小上限 {limit_mb}MB")

    original_name = file.filename or "unnamed"
    suffix = Path(original_name).suffix
    file_id = str(uuid.uuid4())
    stored_name = f"{file_id}{suffix}"
    uploads_dir = resolve_path(get_config("data_dir", "./data")) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / stored_name).write_bytes(data)

    with session_scope() as db:
        db.add(UploadedFile(
            file_id=file_id,
            original_name=original_name,
            stored_path=f"uploads/{stored_name}",
            file_size=len(data),
        ))
    return {"file_id": file_id, "original_name": original_name, "file_size": len(data)}


@router.delete("/api/v1/files/{file_id}")
def delete_file(file_id: str):
    with session_scope() as db:
        row = db.get(UploadedFile, file_id)
        if row is None:
            raise ApiError("NOT_FOUND", f"文件 {file_id} 不存在")
        db.delete(row)
    disk = resolve_path(get_config("data_dir", "./data")) / row.stored_path
    if disk.is_file():
        disk.unlink(missing_ok=True)
    return {"deleted": file_id}
