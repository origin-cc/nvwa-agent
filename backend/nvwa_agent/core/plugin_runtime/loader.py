"""插件模块加载与生命周期钩子执行（§3.7.1）。

- on_load 必须返回插件实例（类型与 plugin.json type 一致），否则 PLUGIN_LOAD_FAILED；
- 钩子路径格式：./main.py::函数名；
- 每次加载使用全新模块名，支持版本升级后的重新导入。
"""
import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any

from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.paths import BACKEND_ROOT
from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.sdk.base import BaseAgentPlugin, BaseToolPlugin
from nvwa_agent.sdk.context import PluginContext

_log = get_core_logger()


class PluginLoadError(Exception):
    """加载失败：携带错误码（PLUGIN_LOAD_FAILED / PLUGIN_HOOK_ERROR）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _parse_hook_path(hook_path: str, base_dir: Path) -> tuple[Path, str]:
    file_part, func_name = hook_path.split("::", 1)
    file_path = (base_dir / file_part.lstrip("./")).resolve()
    return file_path, func_name


def _import_module(file_path: Path, plugin_id: str) -> Any:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))  # 插件可 import nvwa_agent.sdk
    module_name = f"nvwa_plugin_{plugin_id}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise PluginLoadError("PLUGIN_LOAD_FAILED", f"无法加载模块文件 {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def execute_on_load(meta: PluginMeta, ctx: PluginContext) -> BaseAgentPlugin | BaseToolPlugin:
    """执行 on_load 钩子并校验返回实例类型。"""
    hook_path = meta.lifecycle.get("on_load")
    if not hook_path:
        raise PluginLoadError("PLUGIN_LOAD_FAILED", f"插件 {meta.plugin_id} 缺少 lifecycle.on_load")
    try:
        file_path, func_name = _parse_hook_path(hook_path, meta.dir_path)
        module = _import_module(file_path, meta.plugin_id)
        func = getattr(module, func_name, None)
        if not callable(func):
            raise AttributeError(f"入口函数 {func_name} 不存在")
        instance = func(ctx)
    except PluginLoadError:
        raise
    except Exception as exc:
        raise PluginLoadError("PLUGIN_LOAD_FAILED", f"插件 {meta.plugin_id} 加载失败: {exc}") from exc

    expected = BaseAgentPlugin if meta.is_agent else BaseToolPlugin
    if not isinstance(instance, expected):
        raise PluginLoadError(
            "PLUGIN_LOAD_FAILED",
            f"插件 {meta.plugin_id} on_load 返回类型 {type(instance).__name__} 与声明的 "
            f"{meta.type}（须为 {expected.__name__}）不一致",
        )
    return instance


def execute_hook(meta: PluginMeta, hook_name: str, ctx: PluginContext | None) -> None:
    """执行可选钩子（on_activate/on_deactivate/on_unload）；未声明则跳过。"""
    hook_path = meta.lifecycle.get(hook_name)
    if not hook_path:
        return
    try:
        file_path, func_name = _parse_hook_path(hook_path, meta.dir_path)
        # 可选钩子与 on_load 同文件：优先复用已注册模块，失败则重新导入
        module = _import_module(file_path, meta.plugin_id)
        func = getattr(module, func_name, None)
        if not callable(func):
            raise AttributeError(f"钩子函数 {func_name} 不存在")
        func(ctx)
    except Exception as exc:
        raise PluginLoadError("PLUGIN_HOOK_ERROR", f"插件 {meta.plugin_id} {hook_name} 执行失败: {exc}") from exc
