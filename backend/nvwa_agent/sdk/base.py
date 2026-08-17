"""插件基类与统一返回结构（§3.7.3 / §3.7.4）。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅类型提示使用，避免 sdk 硬依赖 langgraph 运行时
    from langgraph.graph.state import CompiledStateGraph

    from nvwa_agent.sdk.context import PluginContext


@dataclass
class ToolResult:
    """工具统一返回结构。

    ok=True 时 data -> tool:result.result；ok=False 时 error_code/error_msg -> tool:error。
    """

    ok: bool
    data: dict | str | None = None
    error_code: str | None = None
    error_msg: str | None = None

    @classmethod
    def success(cls, data: dict | str | None = None) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error_code: str, error_msg: str) -> "ToolResult":
        return cls(ok=False, error_code=error_code, error_msg=error_msg)


class BaseAgentPlugin(ABC):
    """Agent 插件基类：on_load 必须返回本类实例（backend_agent）。"""

    system_prompt: str = ""

    @abstractmethod
    def build_graph(self, ctx: "PluginContext") -> "CompiledStateGraph":
        """构建 LangGraph StateGraph（think→tool_call→tool_observe→…→final_answer）。

        on_load 返回实例后、插件进入 loaded 状态前由 PluginRuntime 调用一次；
        final_answer 节点输出由运行时转 task:finish.result。
        """


class BaseToolPlugin(ABC):
    """工具插件基类：on_load 必须返回本类实例（backend_tool）。"""

    tool_name: str = ""            # 工具调用名，全局唯一，建议 plugin_id:动词
    description: str = ""          # 供 LLM function calling 的工具描述
    parameters_schema: dict = {}   # 参数 JSON Schema

    @abstractmethod
    def execute(self, ctx: "PluginContext", args: dict) -> ToolResult:
        """执行工具；抛出异常由运行时捕获转 tool:error（TOOL_EXEC_ERROR）。

        文件访问必须走 ctx.fs（白名单约束），禁止直接 open() 系统路径。
        """
