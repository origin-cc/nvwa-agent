"""审计事件查询 API（v1.0 §7）：session_event_log 只读追加日志查询。"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_

from nvwa_agent.database import get_db
from nvwa_agent.models.task import SessionEventLog

router = APIRouter(tags=["审计"])


def _parse_time(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


@router.get("/api/v1/audit/events")
def list_audit_events(
    task_id: str | None = Query(None),
    event_type: str | None = Query(None),
    plugin_id: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
):
    """多维过滤 + 分页查询审计事件（按 event_time 倒序，§7.2）。"""
    query = db.query(SessionEventLog)
    if task_id:
        query = query.filter(SessionEventLog.task_id == task_id)
    if event_type:
        query = query.filter(SessionEventLog.event_type == event_type)
    if start:
        query = query.filter(SessionEventLog.event_time >= _parse_time(start))
    if end:
        query = query.filter(SessionEventLog.event_time <= _parse_time(end))
    if plugin_id:
        # 插件维度字段：json_extract 提取 plugin_id / agent_id / tool_id（§7.2）
        query = query.filter(or_(
            func.json_extract(SessionEventLog.event_payload, "$.plugin_id") == plugin_id,
            func.json_extract(SessionEventLog.event_payload, "$.agent_id") == plugin_id,
            func.json_extract(SessionEventLog.event_payload, "$.tool_id") == plugin_id,
        ))

    total = query.count()
    rows = (
        query.order_by(SessionEventLog.event_time.desc(), SessionEventLog.log_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    events = [
        {
            "log_id": r.log_id,
            "task_id": r.task_id,
            "event_type": r.event_type,
            "event_payload": _loads(r.event_payload),
            "event_time": r.event_time.isoformat() if r.event_time else None,
        }
        for r in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "events": events}


def _loads(text: str | None) -> dict:
    try:
        return json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {"raw": text}
