"""其余表：uploaded_file(§7.11) / ui_plugin_state(§7.12) / system_config(§7.8) / agent_profile(§7.4)。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nvwa_agent.database import Base, utcnow


class UploadedFile(Base):
    """上传文件表。"""
    __tablename__ = "uploaded_file"

    file_id: Mapped[str] = mapped_column(String, primary_key=True)
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)  # data/uploads/ 下相对路径
    file_size: Mapped[int | None] = mapped_column(Integer)
    upload_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UiPluginState(Base):
    """UI插件私有状态持久化表：按 plugin_id 隔离，仅该插件可读写。"""
    __tablename__ = "ui_plugin_state"

    plugin_id: Mapped[str] = mapped_column(String, primary_key=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SystemConfig(Base):
    """系统全局配置表：value 为 JSON 序列化字符串；快照加载不修改本表。"""
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class AgentProfile(Base):
    """插件组合快照表：预置与自定义快照存储逻辑一致，无系统特权。"""
    __tablename__ = "agent_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_preset: Mapped[int] = mapped_column(Integer, default=0)  # 0自定义 1预置示例
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
