"""后端插件SDK（§3.7）：随主程序发布的插件开发契约，社区插件唯一入口。

插件只能通过本包访问系统能力；禁止 import nvwa_agent 内核非 sdk 模块。
"""
from nvwa_agent.sdk.base import BaseAgentPlugin, BaseToolPlugin, ToolResult
from nvwa_agent.sdk.context import (
    BaseFileAccessor,
    BaseLlmClient,
    BaseToolCaller,
    EventEmitter,
    FileAccessor,
    LlmClient,
    PluginContext,
    PluginLogger,
    ToolCaller,
    ToolForbiddenError,
)

__all__ = [
    "BaseAgentPlugin", "BaseToolPlugin", "ToolResult",
    "PluginContext", "LlmClient", "ToolCaller", "EventEmitter",
    "FileAccessor", "PluginLogger", "ToolForbiddenError",
    "BaseLlmClient", "BaseToolCaller", "BaseFileAccessor",
]
