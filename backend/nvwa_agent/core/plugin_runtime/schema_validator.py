"""plugin.json Schema 校验器（§5）：jsonschema Draft-07 + 语义补充校验。"""
import json
import re
from pathlib import Path

from jsonschema import Draft7Validator

# §5 JSON Schema（补充 owner_agent_id：PRD 附录B 双向声明校验所需）
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
    },
}

_validator = Draft7Validator(_SCHEMA)
_HOOK_RE = re.compile(r"^(\./[^:]+\.py)::([A-Za-z_][A-Za-z0-9_]*)$")


def validate_plugin_json(raw: dict, source: str = "") -> list[str]:
    """返回错误列表；空列表代表校验通过。错误码归类 PLUGIN_SCHEMA_INVALID。"""
    errors: list[str] = []
    for e in sorted(_validator.iter_errors(raw), key=lambda x: list(x.absolute_path)):
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"{loc}: {e.message}")
    if errors:
        return errors

    ptype = raw["type"]

    # 语义校验：生命周期钩子路径格式 ./xxx.py::func
    lifecycle = raw.get("lifecycle", {})
    for hook in ("on_load", "on_activate", "on_deactivate", "on_unload"):
        path = lifecycle.get(hook)
        if path is not None and not _HOOK_RE.match(path):
            errors.append(f"lifecycle.{hook}: 钩子路径格式必须为 ./xxx.py::函数名，当前为 {path}")

    if ptype in ("backend_agent", "backend_tool"):
        if "on_load" not in lifecycle:
            errors.append("lifecycle.on_load: 后端插件必填")
        if "ui" in raw:
            errors.append("ui: 仅 ui_page_plugin / ui_component_plugin 允许声明 ui 字段")

    if ptype == "backend_tool" and "private_tool_ids" in raw:
        errors.append("private_tool_ids: 仅 backend_agent 允许声明")

    if ptype == "ui_page_plugin":
        ui = raw.get("ui") or {}
        if not ui.get("entry"):
            errors.append("ui.entry: 页面插件必填")
        if not ui.get("route_path"):
            errors.append("ui.route_path: 页面插件必填")
        elif not ui["route_path"].startswith("/"):
            errors.append("ui.route_path: 必须以 / 开头")

    if ptype == "ui_component_plugin":
        ui = raw.get("ui") or {}
        if not ui.get("entry"):
            errors.append("ui.entry: 组件插件必填")
        if not ui.get("target_slot"):
            errors.append("ui.target_slot: 组件插件必填")

    if source and errors:
        return [f"[{source}] {msg}" for msg in errors]
    return errors


def load_and_validate(file: Path) -> tuple[dict | None, list[str]]:
    """读取并校验 plugin.json；返回 (raw, errors)。"""
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:  # json 解析失败 / 文件损坏
        return None, [f"[{file}] plugin.json 解析失败: {exc}"]
    if not isinstance(raw, dict):
        return None, [f"[{file}] plugin.json 根节点必须是对象"]
    return raw, validate_plugin_json(raw)
