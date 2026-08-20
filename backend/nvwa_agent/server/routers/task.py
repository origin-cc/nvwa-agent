"""任务管理 API（§9 任务与会话）：submit/list/detail/log。"""
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from nvwa_agent.database import get_db, session_scope
from nvwa_agent.models.task import Conversation, SessionEventLog, TaskRecord, UiStateSnapshot
from nvwa_agent.server.errors import ApiError

router = APIRouter(tags=["任务"])


class TaskSubmitBody(BaseModel):
    prompt: str
    file_ids: list[str] = []
    conversation_id: str | None = None


class UiStateItem(BaseModel):
    plugin_id: str
    state: dict


class UiStateSnapshotBody(BaseModel):
    event_seq: int
    event_type: str | None = None
    states: list[UiStateItem]


def _enqueue(task_id: str) -> None:
    """任务入队（M3 调度器提供；缺失时任务保持 pending 待后续扫描）。"""
    try:
        from nvwa_agent.core.scheduler.queue import enqueue
        enqueue(task_id)
    except ImportError:
        pass


@router.post("/api/v1/task/submit")
def submit_task(body: TaskSubmitBody):
    if not body.prompt or not body.prompt.strip():
        raise ApiError("VALIDATION_ERROR", "prompt 不能为空")
    conversation_id = body.conversation_id
    with session_scope() as db:
        if conversation_id:
            if db.get(Conversation, conversation_id) is None:
                raise ApiError("NOT_FOUND", f"会话 {conversation_id} 不存在")
        else:  # 缺省自动创建新会话
            conversation_id = str(uuid.uuid4())
            db.add(Conversation(conversation_id=conversation_id, title="新会话"))
        task_id = str(uuid.uuid4())
        db.add(TaskRecord(
            task_id=task_id,
            conversation_id=conversation_id,
            status="pending",
            input_prompt=body.prompt,
            file_ids=json.dumps(body.file_ids or []),
        ))
    _enqueue(task_id)
    return {"task_id": task_id, "status": "pending", "conversation_id": conversation_id}


@router.get("/api/v1/task/list")
def list_tasks(
    conversation_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
):
    base = db.query(TaskRecord)
    if conversation_id:
        base = base.filter(TaskRecord.conversation_id == conversation_id)
    total = base.count()
    rows = (
        base.order_by(TaskRecord.created_at.desc(), TaskRecord.task_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    tasks = [_task_brief(r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "tasks": tasks}


@router.get("/api/v1/task/{task_id}")
def get_task(task_id: str, db=Depends(get_db)):
    row = db.get(TaskRecord, task_id)
    if row is None:
        raise ApiError("NOT_FOUND", f"任务 {task_id} 不存在")
    detail = _task_brief(row)
    detail.update({
        "file_ids": _loads(row.file_ids, []),
        "active_agent_ids": _loads(row.active_agent_ids, []),
        "error_msg": row.error_msg,
    })
    return detail


@router.post("/api/v1/task/{task_id}/cancel")
def cancel_task(task_id: str):
    """取消任务（前端停止按钮，§10）：标记取消信号，Worker 检测后中断流式推理。"""
    with session_scope() as db:
        if db.get(TaskRecord, task_id) is None:
            raise ApiError("NOT_FOUND", f"任务 {task_id} 不存在")
    from nvwa_agent.core.scheduler.queue import cancel_task as _cancel_task

    _cancel_task(task_id)
    return {"task_id": task_id, "status": "cancelling"}


@router.get("/api/v1/task/{task_id}/log")
def get_task_log(task_id: str, db=Depends(get_db)):
    """该任务全部 session_event_log 事件（按时间线），供任务回放。

    会话删除后 task_record 级联删除，日志保留悬空 task_id 供审计回放
    （PRD 3.5.2/§6.2-8）：任务不存在时仍返回日志（可为空），不报404。
    """
    task = db.get(TaskRecord, task_id)
    rows = (
        db.query(SessionEventLog)
        .filter(SessionEventLog.task_id == task_id)
        .order_by(SessionEventLog.log_id.asc())
        .all()
    )
    events = [
        {
            "log_id": r.log_id,
            "event_type": r.event_type,
            "event_payload": _loads(r.event_payload, {}),
            "event_time": r.event_time.isoformat() if r.event_time else None,
        }
        for r in rows
    ]
    return {
        "task_id": task_id,
        "task_deleted": task is None,
        "events": events,
    }


def _task_brief(row: TaskRecord) -> dict:
    return {
        "task_id": row.task_id,
        "conversation_id": row.conversation_id,
        "status": row.status,
        "input_prompt": row.input_prompt,
        "result": row.result,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


@router.post("/api/v1/task/{task_id}/ui-state-snapshot")
def post_ui_state_snapshot(task_id: str, body: UiStateSnapshotBody):
    """上报任务执行期间的组件状态快照（v1.0 §12.1）。"""
    with session_scope() as db:
        if db.get(TaskRecord, task_id) is None:
            raise ApiError("NOT_FOUND", f"任务 {task_id} 不存在")
        for item in body.states:
            db.add(UiStateSnapshot(
                task_id=task_id,
                event_seq=body.event_seq,
                event_type=body.event_type,
                plugin_id=item.plugin_id,
                state_json=json.dumps(item.state, ensure_ascii=False),
            ))
    return {"accepted": True, "snapshot_count": len(body.states)}


@router.get("/api/v1/task/{task_id}/ui-state-snapshots")
def get_ui_state_snapshots(task_id: str, db=Depends(get_db)):
    """获取任务组件状态快照序列（按 event_seq 升序，v1.0 §12.1）。"""
    rows = (
        db.query(UiStateSnapshot)
        .filter(UiStateSnapshot.task_id == task_id)
        .order_by(UiStateSnapshot.event_seq.asc(), UiStateSnapshot.snapshot_id.asc())
        .all()
    )
    snapshots = [
        {
            "event_seq": r.event_seq,
            "event_type": r.event_type,
            "plugin_id": r.plugin_id,
            "state": _loads(r.state_json, {}),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"snapshots": snapshots}


def _loads(text: str | None, default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default
