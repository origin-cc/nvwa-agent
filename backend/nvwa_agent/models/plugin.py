"""插件表：agent_plugin(§7.1) / tool_config(§7.2) / ui_plugin(§7.3)。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nvwa_agent.database import Base, utcnow


class AgentPlugin(Base):
    """后端智能体插件表。"""
    __tablename__ = "agent_plugin"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False, default="backend_agent")
    version: Mapped[str] = mapped_column(String, nullable=False, default="1.0.0")
    state: Mapped[str] = mapped_column(String, nullable=False, default="loaded")
    bind_ui_plugin_id: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    dependencies: Mapped[str | None] = mapped_column(Text)        # JSON数组
    private_tool_ids: Mapped[str | None] = mapped_column(Text)    # JSON数组
    model_params: Mapped[str | None] = mapped_column(Text)        # JSON对象
    plugin_config: Mapped[str | None] = mapped_column(Text)       # JSON对象
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ToolConfig(Base):
    """工具插件表：owner_agent_id 为空代表全局工具。"""
    __tablename__ = "tool_config"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False, default="backend_tool")
    version: Mapped[str] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="loaded")
    owner_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    bind_ui_plugin_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dependencies: Mapped[str | None] = mapped_column(Text)        # JSON数组
    plugin_config: Mapped[str | None] = mapped_column(Text)       # JSON对象
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UiPlugin(Base):
    """前端UI插件表：route_path 全表UNIQUE（SQLite 下 NULL 不参与唯一性）。"""
    __tablename__ = "ui_plugin"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # ui_page_plugin / ui_component_plugin
    version: Mapped[str] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="loaded")
    bind_backend_plugin_id: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    dependencies: Mapped[str | None] = mapped_column(Text)        # JSON数组
    route_path: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    slots: Mapped[str | None] = mapped_column(Text)               # JSON数组，页面插件声明
    target_slot: Mapped[str | None] = mapped_column(Text)         # 组件插件目标插槽
    entry_path: Mapped[str | None] = mapped_column(Text)          # 编译产物入口相对路径
    plugin_config: Mapped[str | None] = mapped_column(Text)       # JSON对象
    error_msg: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
