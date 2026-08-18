"""plugin.json 三层校验器（§5 + v1.0 §3）。

- 第1层 结构校验（JSON Schema Draft-07）→ PLUGIN_SCHEMA_INVALID
- 第2层 字段值校验（§3.2 值域/格式）→ PLUGIN_METADATA_INVALID
- 第3层 交叉引用与存在性校验（§3.3）→ PLUGIN_METADATA_INVALID（或沿用专项码）
"""
import ast
import json
import re
from pathlib import Path

from jsonschema import Draft7Validator

# §5 JSON Schema（结构层：类型/枚举/必填/pattern）
_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["id", "name", "version", "type", "description", "author"],
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9-_]+$"},
        "name": {"type": "string"},
        "version": {"type": "string"},
        "type": {"type": "string",
                 "enum": ["backend_agent", "backend_tool",
                          "ui_page_plugin", "ui_component_plugin"]},
        "description": {"type": "string"},
        "author": {"type": "string"},
        "bind_ui_plugin_id": {"type": "string"},
        "bind_backend_plugin_id": {"type": "string"},
        "owner_agent_id": {"type": "string",
                           "description": "私有工具归属Agent id，backend_tool专用"},
        "priority": {"type": "integer", "default": 50},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "private_tool_ids": {"type": "array", "items": {"type": "string"}},
        "model_params": {
            "type": "object",
            "properties": {
                "model_path": {"type": "string"},
                "temperature": {"type": "number"},
                "max_tokens": {"type": "integer"},
                "top_p": {"type": "number"},
                "stop_sequences": {"type": "array", "items": {"type": "string"}},
            },
        },
        "lifecycle": {
            "type": "object",
            "properties": {
                "on_load": {"type": "string"},
                "on_activate": {"type": "string"},
                "on_deactivate": {"type": "string"},
                "on_unload": {"type": "string"},
            },
        },
        "ui": {
            "type": "object",
            "properties": {
                "entry": {"type": "string"},
                "route_path": {"type": "string"},
                "slots": {"type": "array", "items": {"type": "string"}},
                "target_slot": {"type": "string"},
            },
        },
        "config": {"type": "object"},
        "file_permissions": {
            "type": "object",
            "properties": {
                "read_dirs": {"type": "array", "items": {"type": "string"}},
                "write_dirs": {"type": "array", "items": {"type": "string"}},
                "allow_delete": {"type": "boolean"},
            },
        },
    },
}

_validator = Draft7Validator(_SCHEMA)
_HOOK_RE = re.compile(r"^(\./[^:]+\.py)::([A-Za-z_][A-Za-z0-9_]*)$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


# ---------------------------------------------------------------------------
# 第1层：结构校验（JSON Schema）→ PLUGIN_SCHEMA_INVALID
# ---------------------------------------------------------------------------
def validate_plugin_json(raw: dict, source: str = "") -> list[str]:
    """仅 JSON Schema 结构校验；空列表代表通过。"""
    errors: list[str] = []
    for e in sorted(_validator.iter_errors(raw), key=lambda x: list(x.absolute_path)):
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"{loc}: {e.message}")
    if source and errors:
        return [f"[{source}] {msg}" for msg in errors]
    return errors


# ---------------------------------------------------------------------------
# 第2层：字段值校验（§3.2）→ PLUGIN_METADATA_INVALID
# ---------------------------------------------------------------------------
def validate_plugin_values(raw: dict, dir_name: str | None = None) -> list[str]:
    """对已通过结构校验的字段做值域/格式校验；空列表代表通过。"""
    errors: list[str] = []
    ptype = raw["type"]

    # id 必须与插件目录名一致
    if dir_name is not None and raw.get("id") != dir_name:
        errors.append(f"id: 必须与插件目录名一致（{raw.get('id')} != {dir_name}）")

    # version 语义化版本
    version = raw.get("version")
    if version is None or not _SEMVER_RE.match(str(version)):
        errors.append(f"version: 必须符合语义化版本 x.y.z，当前为 {version}")

    # priority 范围
    priority = raw.get("priority", 50)
    if not (isinstance(priority, int) and 0 <= priority <= 1000):
        errors.append(f"priority: 必须是 0~1000 的整数，当前为 {priority}")

    # dependencies 元素非空、去重
    deps = list(raw.get("dependencies") or [])
    if any(not d or not str(d).strip() for d in deps):
        errors.append("dependencies: 元素不能为空")
    if len(set(deps)) != len(deps):
        errors.append("dependencies: 元素不能重复")

    # private_tool_ids 仅 backend_agent + 元素非空、去重
    if "private_tool_ids" in raw:
        if ptype != "backend_agent":
            errors.append("private_tool_ids: 仅 backend_agent 允许声明")
        else:
            pts = list(raw.get("private_tool_ids") or [])
            if any(not p or not str(p).strip() for p in pts):
                errors.append("private_tool_ids: 元素不能为空")
            if len(set(pts)) != len(pts):
                errors.append("private_tool_ids: 元素不能重复")

    # model_params 仅 backend_agent + 采样参数范围
    if raw.get("model_params"):
        if ptype != "backend_agent":
            errors.append("model_params: 仅 backend_agent 允许声明")
        else:
            mp = raw["model_params"]
            for key in ("temperature", "top_p"):
                val = mp.get(key)
                if val is None:
                    continue
                try:
                    if not (0 <= float(val) <= 2):
                        errors.append(f"model_params.{key}: 必须在 [0,2] 内，当前为 {val}")
                except (TypeError, ValueError):
                    errors.append(f"model_params.{key}: 必须是数值，当前为 {val}")
            max_tokens = mp.get("max_tokens")
            if max_tokens is not None and not (
                isinstance(max_tokens, int) and not isinstance(max_tokens, bool)
                and max_tokens > 0
            ):
                errors.append(f"model_params.max_tokens: 必须为正整数，当前为 {max_tokens}")

    # 生命周期钩子路径格式 ./xxx.py::func
    lifecycle = raw.get("lifecycle") or {}
    for hook in ("on_load", "on_activate", "on_deactivate", "on_unload"):
        path = lifecycle.get(hook)
        if path is not None and not _HOOK_RE.match(path):
            errors.append(f"lifecycle.{hook}: 钩子路径格式必须为 ./xxx.py::函数名，当前为 {path}")

    if ptype in ("backend_agent", "backend_tool"):
        if "on_load" not in lifecycle:
            errors.append("lifecycle.on_load: 后端插件必填")
        if "ui" in raw:
            errors.append("ui: 仅 ui_page_plugin / ui_component_plugin 允许声明 ui 字段")

    if ptype in ("ui_page_plugin", "ui_component_plugin"):
        ui = raw.get("ui") or {}
        entry = ui.get("entry")
        if not entry or not str(entry).strip():
            errors.append("ui.entry: UI 插件必填且相对路径非空")

    if ptype == "ui_page_plugin":
        ui = raw.get("ui") or {}
        if not ui.get("route_path"):
            errors.append("ui.route_path: 页面插件必填")
        elif not str(ui["route_path"]).startswith("/"):
            errors.append("ui.route_path: 必须以 / 开头")
        if "target_slot" in ui:
            errors.append("ui.target_slot: 仅 ui_component_plugin 允许声明")
        slots = list(ui.get("slots") or [])
        if any(not s or not str(s).strip() for s in slots):
            errors.append("ui.slots: 元素不能为空")
        if len(set(slots)) != len(slots):
            errors.append("ui.slots: 元素不能重复")

    if ptype == "ui_component_plugin":
        ui = raw.get("ui") or {}
        if not ui.get("target_slot"):
            errors.append("ui.target_slot: 组件插件必填")
        if "slots" in ui:
            errors.append("ui.slots: 仅 ui_page_plugin 允许声明")

    # file_permissions 仅 backend 插件可声明 + 目录数组非空去重（§4.2）
    if "file_permissions" in raw:
        if ptype not in ("backend_agent", "backend_tool"):
            errors.append("file_permissions: 仅 backend_agent / backend_tool 允许声明")
        else:
            fp = raw.get("file_permissions") or {}
            for key in ("read_dirs", "write_dirs"):
                dirs = list(fp.get(key) or [])
                if any(not d or not str(d).strip() for d in dirs):
                    errors.append(f"file_permissions.{key}: 元素不能为空")
                if len(set(dirs)) != len(dirs):
                    errors.append(f"file_permissions.{key}: 元素不能重复")

    return errors


# ---------------------------------------------------------------------------
# 第3层：交叉引用与存在性校验（§3.3）→ (errors, warnings)
# ---------------------------------------------------------------------------
def validate_plugin_refs(raw: dict, dir_path: Path,
                         plugins_root: Path | None = None) -> tuple[list[str], list[str]]:
    """钩子/入口文件存在性 + 绑定引用存在性；返回 (errors, warnings)。

    errors -> PLUGIN_METADATA_INVALID；warnings 仅告警不阻断（§3.3 第5条）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    ptype = raw["type"]

    # 生命周期钩子路径可解析：模块文件存在、函数名存在
    lifecycle = raw.get("lifecycle") or {}
    for hook, path in lifecycle.items():
        if not isinstance(path, str) or "::" not in path:
            continue  # 格式错误已由字段值校验捕获
        file_part, func_name = path.split("::", 1)
        file_path = (dir_path / file_part.lstrip("./")).resolve()
        if not file_path.is_file():
            errors.append(f"lifecycle.{hook}: 钩子模块文件不存在 {path}")
        elif not _module_has_func(file_path, func_name):
            errors.append(f"lifecycle.{hook}: 函数 {func_name} 不存在于 {path}")

    # ui.entry 编译产物文件必须存在
    if ptype in ("ui_page_plugin", "ui_component_plugin"):
        entry = (raw.get("ui") or {}).get("entry")
        if entry and str(entry).strip():
            entry_path = (dir_path / str(entry).lstrip("./")).resolve()
            if not entry_path.is_file():
                errors.append(f"ui.entry: 编译产物文件不存在 {entry}")

    # 绑定引用存在性：仅告警，不阻断（对齐 v0.1 §11 场景2）
    if plugins_root is not None:
        for field in ("bind_ui_plugin_id", "bind_backend_plugin_id"):
            target = raw.get(field)
            if target and not (plugins_root / target / "plugin.json").is_file():
                warnings.append(f"{field}: 引用的插件 {target} 不存在（仅告警）")

    return errors, warnings


def _module_has_func(file_path: Path, func_name: str) -> bool:
    """静态解析 Python 源码，判断指定函数名是否存在。"""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == func_name
        for node in ast.walk(tree)
    )


# ---------------------------------------------------------------------------
# 读取入口
# ---------------------------------------------------------------------------
def load_plugin_json(file: Path) -> tuple[dict | None, list[str]]:
    """读取 plugin.json；返回 (raw, 解析错误列表)。"""
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:  # json 解析失败 / 文件损坏
        return None, [f"[{file}] plugin.json 解析失败: {exc}"]
    if not isinstance(raw, dict):
        return None, [f"[{file}] plugin.json 根节点必须是对象"]
    return raw, []
