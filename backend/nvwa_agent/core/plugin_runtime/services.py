"""插件上下文服务实现：注入 PluginContext 的真实能力对象（§3.7.2）。"""
import json

from nvwa_agent.core import taskctx
from nvwa_agent.core.llm import get_llm_client, merge_model_params
from nvwa_agent.core.log import get_plugin_logger
from nvwa_agent.core.paths import resolve_path
from nvwa_agent.core.plugin_runtime.event_bus import event_bus
from nvwa_agent.config import get as get_config
from nvwa_agent.database import session_scope
from nvwa_agent.models.misc import SystemConfig
from nvwa_agent.models.plugin import AgentPlugin, ToolConfig, UiPlugin
from nvwa_agent.sdk.context import (
    BaseEventEmitter,
    BaseFileAccessor,
    BaseKnowledgeAccessor,
    BaseLlmClient,
    BasePluginLogger,
    BaseToolCaller,
    FilePermissionError,
    PluginContext,
    ToolForbiddenError,
)

_PLUGIN_LOG = get_plugin_logger()


class LlmServiceImpl(BaseLlmClient):
    """LLM 服务：合并采样参数；流式分片自动转 agent:think 事件（§8 事件10）。"""

    def __init__(self, agent_id: str, model_params: dict | None) -> None:
        self._agent_id = agent_id
        self._params = merge_model_params(model_params)

    def chat(self, messages: list[dict], stream: bool = True):
        client = get_llm_client(self._params)
        if not stream:
            return client.chat(messages, stream=False)

        def _stream():
            seq = 0
            for shard in client.chat(messages, stream=True):
                seq += 1
                event_bus.publish("agent:think", {
                    "task_id": taskctx.get_current_task(),
                    "agent_id": self._agent_id,
                    "seq": seq,
                    "is_final": False,
                    "think_content": shard,
                })
                yield shard
            event_bus.publish("agent:think", {
                "task_id": taskctx.get_current_task(),
                "agent_id": self._agent_id,
                "seq": seq + 1,
                "is_final": True,
                "think_content": "",
            })

        return _stream()


class ToolCallerImpl(BaseToolCaller):
    """工具调用入口：权限/状态校验在 PluginRuntime.call_tool 统一执行。"""

    def __init__(self, caller_agent_id: str) -> None:
        self._caller = caller_agent_id

    def call(self, tool_id: str, args: dict) -> dict:
        from nvwa_agent.core.plugin_runtime.runtime import get_runtime  # 延迟导入避免循环

        return get_runtime().call_tool(tool_id, args, self._caller)


class EventEmitterImpl(BaseEventEmitter):
    """自定义事件：强制以插件自身 id 为前缀，防止污染系统契约事件名。"""

    def __init__(self, plugin_id: str) -> None:
        self._plugin_id = plugin_id

    def emit(self, event_type: str, payload: dict) -> None:
        if not event_type.startswith(f"{self._plugin_id}:"):
            raise ValueError(
                f"自定义事件名必须以插件id为前缀（{self._plugin_id}:xxx），当前为 {event_type}"
            )
        event_bus.publish(event_type, payload)


class FileAccessorImpl(BaseFileAccessor):
    """白名单目录内文件读写（§14 + v1.0 §4 精细化权限）。

    - 全局白名单为硬边界；
    - 插件声明 file_permissions 时按 read/write/delete 操作维度精细化；
    - 未声明 file_permissions 时继承全局白名单能力（向后兼容 v0.1）。
    """

    def __init__(self, plugin_id: str, file_permissions: dict | None = None) -> None:
        self._plugin_id = plugin_id
        self._perms = file_permissions or {}

    @staticmethod
    def _whitelist() -> list:
        return [resolve_path(p) for p in get_config("file_access_whitelist_dirs", [])]

    @staticmethod
    def _resolve(path: str):
        from pathlib import Path

        target = Path(path)
        if not target.is_absolute():
            target = resolve_path(path)
        return target.resolve()

    def _check(self, path: str, op: str):
        """§4.4 校验流程：规范化 → 全局白名单 → 插件 file_permissions。"""
        resolved = self._resolve(path)
        if not any(resolved == w or w in resolved.parents for w in self._whitelist()):
            raise FilePermissionError(f"路径不在全局白名单目录内: {path}")
        if self._perms:
            if op == "read":
                allowed = self._perms.get("read_dirs") or []
            elif op == "write":
                allowed = self._perms.get("write_dirs") or []
            elif op == "delete":
                if not self._perms.get("allow_delete"):
                    raise FilePermissionError("插件未声明 allow_delete，禁止删除文件")
                allowed = self._perms.get("write_dirs") or []
            else:
                allowed = []
            allowed_resolved = [self._resolve(d) for d in allowed]
            if not any(resolved == a or a in resolved.parents for a in allowed_resolved):
                raise FilePermissionError(f"路径不在插件 {op} 权限目录内: {path}")
        return resolved

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self._check(path, "read").read_text(encoding=encoding)

    def write_text(self, path: str, content: str, encoding: str = "utf-8") -> str:
        target = self._check(path, "write")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return str(target)

    def list_dir(self, path: str) -> list[str]:
        return sorted(p.name for p in self._check(path, "read").iterdir())

    def delete(self, path: str) -> None:
        target = self._check(path, "delete")
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            target.rmdir()  # 仅删除空目录，避免误删
        else:
            raise FileNotFoundError(f"路径不存在: {path}")


class KnowledgeAccessorImpl(BaseKnowledgeAccessor):
    """知识库检索（§12.4）：Embedding 不可用时抛出友好错误。"""

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        from nvwa_agent.core.knowledge.embedding import EmbeddingUnavailable
        from nvwa_agent.core.knowledge.service import get_knowledge_service

        try:
            return get_knowledge_service().search(query, top_k=top_k)
        except EmbeddingUnavailable as exc:
            raise RuntimeError(f"知识库检索不可用：{exc}") from exc


class PluginLoggerImpl(BasePluginLogger):
    """插件日志器：自动携带 plugin_id 前缀，写入 backend_plugin-*.log。"""

    def __init__(self, plugin_id: str) -> None:
        self._prefix = f"[{plugin_id}]"

    def info(self, msg: str) -> None:
        _PLUGIN_LOG.info("%s %s", self._prefix, msg)

    def warning(self, msg: str) -> None:
        _PLUGIN_LOG.warning("%s %s", self._prefix, msg)

    def error(self, msg: str, exc: Exception | None = None) -> None:
        if exc is not None:
            _PLUGIN_LOG.error("%s %s", self._prefix, msg, exc_info=exc)
        else:
            _PLUGIN_LOG.error("%s %s", self._prefix, msg)


def load_plugin_user_config(plugin_id: str, ptype: str) -> dict:
    """读取用户面板修改过的插件业务配置（快照保存内容）。"""
    model = {"backend_agent": AgentPlugin, "backend_tool": ToolConfig}.get(ptype, UiPlugin)
    with session_scope() as db:
        row = db.get(model, plugin_id)
        if row is None or not row.plugin_config:
            return {}
        try:
            return json.loads(row.plugin_config)
        except (TypeError, json.JSONDecodeError):
            return {}


def build_context(meta) -> PluginContext:
    """构造插件运行上下文：config = plugin.json config + 用户面板修改值。"""
    user_cfg = load_plugin_user_config(meta.plugin_id, meta.type)
    merged = {**meta.config, **user_cfg}
    return PluginContext(
        plugin_id=meta.plugin_id,
        config=merged,
        llm=LlmServiceImpl(meta.plugin_id, meta.model_params if meta.is_agent else None),
        tools=ToolCallerImpl(meta.plugin_id),
        events=EventEmitterImpl(meta.plugin_id),
        fs=FileAccessorImpl(meta.plugin_id, getattr(meta, "file_permissions", None)),
        logger=PluginLoggerImpl(meta.plugin_id),
        kb=KnowledgeAccessorImpl(),
    )
