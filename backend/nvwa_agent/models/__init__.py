"""ORM 模型汇总注册（14张表 + 索引/约束）。"""
from nvwa_agent.models.plugin import AgentPlugin, ToolConfig, UiPlugin
from nvwa_agent.models.task import (
    Conversation,
    ConversationSummary,
    SessionEventLog,
    TaskRecord,
    UiStateSnapshot,
)
from nvwa_agent.models.knowledge import DocChunk, KnowledgeDoc
from nvwa_agent.models.misc import AgentProfile, SystemConfig, UiPluginState, UploadedFile

__all__ = [
    "AgentPlugin", "ToolConfig", "UiPlugin",
    "Conversation", "TaskRecord", "SessionEventLog", "UiStateSnapshot",
    "ConversationSummary",
    "KnowledgeDoc", "DocChunk",
    "UploadedFile", "UiPluginState", "SystemConfig", "AgentProfile",
]
