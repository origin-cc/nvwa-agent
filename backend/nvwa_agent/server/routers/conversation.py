"""会话管理 API（§9 任务与会话）。"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from nvwa_agent.database import get_db, session_scope
from nvwa_agent.models.task import Conversation, TaskRecord
from nvwa_agent.server.errors import ApiError

router = APIRouter(tags=["会话"])


class ConversationCreateBody(BaseModel):
    title: str | None = None


class ConversationRenameBody(BaseModel):
    title: str


@router.get("/api/v1/conversation/list")
def list_conversations(db=Depends(get_db)):
    stmt = (
        select(
            Conversation.conversation_id,
            Conversation.title,
            Conversation.updated_at,
            func.count(TaskRecord.task_id).label("task_count"),
        )
        .outerjoin(TaskRecord, TaskRecord.conversation_id == Conversation.conversation_id)
        .group_by(Conversation.conversation_id)
        .order_by(Conversation.updated_at.desc())
    )
    rows = db.execute(stmt).all()
    conversations = [
        {
            "conversation_id": r.conversation_id,
            "title": r.title,
            "task_count": r.task_count,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
    return {"conversations": conversations}


@router.post("/api/v1/conversation/create")
def create_conversation(body: ConversationCreateBody | None = None):
    title = (body.title if body and body.title else None) or "新会话"
    conversation_id = str(uuid.uuid4())
    with session_scope() as db:
        db.add(Conversation(conversation_id=conversation_id, title=title))
    return {"conversation_id": conversation_id, "title": title}


@router.put("/api/v1/conversation/{conversation_id}")
def rename_conversation(conversation_id: str, body: ConversationRenameBody):
    with session_scope() as db:
        row = db.get(Conversation, conversation_id)
        if row is None:
            raise ApiError("NOT_FOUND", f"会话 {conversation_id} 不存在")
        row.title = body.title
        row.updated_at = datetime.now()
    return {"conversation_id": conversation_id, "title": body.title}


@router.delete("/api/v1/conversation/{conversation_id}")
def delete_conversation(conversation_id: str):
    """级联删除会话内全部 task_record；session_event_log 审计日志保留（§7.6）。"""
    with session_scope() as db:
        row = db.get(Conversation, conversation_id)
        if row is None:
            raise ApiError("NOT_FOUND", f"会话 {conversation_id} 不存在")
        db.query(TaskRecord).filter(TaskRecord.conversation_id == conversation_id).delete()
        db.delete(row)
    return {"deleted": conversation_id}
