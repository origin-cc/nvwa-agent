"""会话与任务表：conversation(§7.5) / task_record(§7.6) / session_event_log(§7.7)。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nvwa_agent.database import Base, utcnow


class Conversation(Base):
    """会话表：对话主页组织任务历史的容器。"""
    __tablename__ = "conversation"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaskRecord(Base):
    """任务记录表：删除会话级联删除任务记录。"""
    __tablename__ = "task_record"
    __table_args__ = (Index("idx_conversation_id", "conversation_id"),)

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversation.conversation_id", ondelete="CASCADE"), nullable=False,
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    input_prompt: Mapped[str | None] = mapped_column(Text)
    file_ids: Mapped[str | None] = mapped_column(Text)          # JSON数组
    active_agent_ids: Mapped[str | None] = mapped_column(Text)  # JSON数组
    result: Mapped[str | None] = mapped_column(Text)            # 最终完整答案
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SessionEventLog(Base):
    """追加式会话事件日志表：只 INSERT，禁止 UPDATE/DELETE。

    task_id 不设外键：会话删除后允许悬空，仅作审计追溯（§7.6说明）。
    """
    __tablename__ = "session_event_log"
    __table_args__ = (Index("idx_task_id", "task_id"),)

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_payload: Mapped[str] = mapped_column(Text, nullable=False)  # 完整payload JSON
    event_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
