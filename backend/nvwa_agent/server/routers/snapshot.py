"""快照管理 API（§6.2 快照管理）：save/load/list/delete/export/import。"""
import json

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from nvwa_agent.core.snapshot import (
    import_snapshot,
    list_snapshots,
    load_snapshot,
    save_snapshot,
)
from nvwa_agent.database import get_db
from nvwa_agent.models.misc import AgentProfile
from nvwa_agent.server.errors import ApiError

router = APIRouter(tags=["快照"])


class SaveRequest(BaseModel):
    name: str


@router.get("/api/v1/snapshot/list")
def get_list():
    return {"snapshots": list_snapshots()}


@router.post("/api/v1/snapshot/save")
def save(req: SaveRequest):
    name = req.name.strip() or "未命名快照"
    snapshot_id = save_snapshot(name)
    return {"snapshot_id": snapshot_id, "name": name}


@router.post("/api/v1/snapshot/{snapshot_id}/load")
def load(snapshot_id: int):
    try:
        result = load_snapshot(snapshot_id)
    except KeyError:
        raise ApiError("NOT_FOUND", f"快照 {snapshot_id} 不存在")
    return result


@router.delete("/api/v1/snapshot/{snapshot_id}")
def delete(snapshot_id: int, db=Depends(get_db)):
    row = db.get(AgentProfile, snapshot_id)
    if row is None:
        raise ApiError("NOT_FOUND", f"快照 {snapshot_id} 不存在")
    db.delete(row)
    db.commit()
    return {"deleted": snapshot_id}


@router.get("/api/v1/snapshot/{snapshot_id}/export")
def export(snapshot_id: int, db=Depends(get_db)):
    row = db.get(AgentProfile, snapshot_id)
    if row is None:
        raise ApiError("NOT_FOUND", f"快照 {snapshot_id} 不存在")
    content = json.dumps(json.loads(row.snapshot_json), ensure_ascii=False, indent=2)
    filename = f"{row.name}.snapshot.json".replace("/", "_").replace("\\", "_")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/v1/snapshot/import")
async def import_json(file: UploadFile):
    data = await file.read()
    try:
        snapshot = json.loads(data.decode("utf-8"))
        plugins = snapshot.get("plugins")
        if not isinstance(plugins, dict):
            raise ValueError("缺少 plugins 字段")
        for kind in ("backend_agents", "backend_tools", "ui_plugins"):
            for entry in plugins.get(kind, []):
                if "plugin_id" not in entry:
                    raise ValueError(f"plugins.{kind} 存在缺少 plugin_id 的条目")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ApiError("VALIDATION_ERROR", f"快照文件格式非法: {exc}")

    meta = snapshot.get("snapshot_meta") or {}
    name = (meta.get("name") or file.filename or "导入快照").removesuffix(".json")
    return import_snapshot(name, snapshot)
