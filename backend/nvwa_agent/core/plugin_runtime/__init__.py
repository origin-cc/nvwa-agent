"""后端插件运行时 PluginRuntime（§3）。"""
from nvwa_agent.core.plugin_runtime.event_bus import EventBus, event_bus
from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.core.plugin_runtime.reconcile import scan_and_reconcile
from nvwa_agent.core.plugin_runtime.runtime import (
    PluginOpError,
    PluginRuntime,
    ToolCallLimitExceeded,
    get_runtime,
)

__all__ = [
    "EventBus", "event_bus", "PluginMeta", "PluginOpError",
    "PluginRuntime", "ToolCallLimitExceeded", "get_runtime", "scan_and_reconcile",
]
