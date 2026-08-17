"""PluginContext 注入服务契约（§3.7.2）。

本文件定义插件可用的服务“接口形状”；真实实现由内核注入
（core/plugin_runtime/services.py），插件只能通过 ctx 访问系统能力。
"""
from abc import ABC, abstractmethod
from typing import Iterator


class ToolForbiddenError(Exception):
    """工具调用被拒绝：不存在 / 被禁用 / 越权（TOOL_FORBIDDEN / TOOL_NOT_FOUND）。"""


class BaseLlmClient(ABC):
    """LLM 推理客户端：采样参数由运行时按全局配置 + plugin.json model_params 合并注入。"""

    @abstractmethod
    def chat(self, messages: list[dict], stream: bool = True) -> Iterator[str] | str:
        """messages 为 OpenAI 风格 [{role, content}]；stream=True 返回增量分片迭代器。"""


class BaseToolCaller(ABC):
    """工具调用入口：仅可调用全局工具与自身 private_tool_ids 内工具。"""

    @abstractmethod
    def call(self, tool_id: str, args: dict) -> dict:
        """返回工具结果 dict；越权/禁用/不存在抛 ToolForbiddenError。"""


class BaseEventEmitter(ABC):
    """自定义事件发射器：事件写入 session_event_log 并经 SSE 外推。"""

    @abstractmethod
    def emit(self, event_type: str, payload: dict) -> None:
        """event_type 必须以插件自身 id 为前缀（如 demo-agent-plugin:progress）。"""


class BaseFileAccessor(ABC):
    """白名单目录内文件读写（§14 路径校验）。"""

    @abstractmethod
    def read_text(self, path: str, encoding: str = "utf-8") -> str: ...

    @abstractmethod
    def write_text(self, path: str, content: str, encoding: str = "utf-8") -> str: ...

    @abstractmethod
    def list_dir(self, path: str) -> list[str]: ...


class BaseKnowledgeAccessor(ABC):
    """知识库检索访问器（§12.4）：全局知识库对所有插件只读开放。"""

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """返回 [{chunk_id, doc_id, file_name, chunk_index, content, score}]。"""


class BasePluginLogger(ABC):
    """插件日志器：自动携带 plugin_id，写入 backend_plugin-*.log（§15）。"""

    @abstractmethod
    def info(self, msg: str) -> None: ...

    @abstractmethod
    def warning(self, msg: str) -> None: ...

    @abstractmethod
    def error(self, msg: str, exc: Exception | None = None) -> None: ...


# ---------------- 运行时注入的类型别名（契约签名对齐 §3.7.2） ----------------
LlmClient = BaseLlmClient
ToolCaller = BaseToolCaller
EventEmitter = BaseEventEmitter
FileAccessor = BaseFileAccessor
PluginLogger = BasePluginLogger


class PluginContext:
    """插件运行上下文：钩子执行前由运行时构造并注入。"""

    def __init__(
        self,
        plugin_id: str,
        config: dict,
        llm: BaseLlmClient,
        tools: BaseToolCaller,
        events: BaseEventEmitter,
        fs: BaseFileAccessor,
        logger: BasePluginLogger,
        kb: BaseKnowledgeAccessor | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.config = config          # plugin.json config 与用户面板修改值的合并配置
        self.llm = llm
        self.tools = tools
        self.events = events
        self.fs = fs
        self.logger = logger
        self.kb = kb                  # 知识库只读访问器（None 时知识库能力不可用）
