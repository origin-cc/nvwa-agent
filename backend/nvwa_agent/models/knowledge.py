"""知识库表：knowledge_doc(§7.9) / doc_chunk(§7.10)。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nvwa_agent.database import Base, utcnow


class KnowledgeDoc(Base):
    """知识库文档表：status = parsing / indexing / ready / failed。"""
    __tablename__ = "knowledge_doc"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="parsing")
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DocChunk(Base):
    """知识库切片表：faiss_index_id 与 FAISS 向量位置一一对应（§12）。"""
    __tablename__ = "doc_chunk"
    __table_args__ = (Index("idx_doc_chunk_doc_id", "doc_id"),)

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String, ForeignKey("knowledge_doc.doc_id", ondelete="CASCADE"), nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    faiss_index_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
