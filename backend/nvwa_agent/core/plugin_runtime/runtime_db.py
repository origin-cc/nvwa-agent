"""插件元数据与数据库行的映射（agent_plugin / tool_config / ui_plugin）。"""
import json

from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.database import session_scope
from nvwa_agent.models.plugin import AgentPlugin, ToolConfig, UiPlugin


def _model_of(ptype: str):
    if ptype == "backend_agent":
        return AgentPlugin
    if ptype == "backend_tool":
        return ToolConfig
    return UiPlugin


def db_get_row(ptype: str, plugin_id: str):
    with session_scope() as db:
        return db.get(_model_of(ptype), plugin_id)


def db_upsert_meta(meta: PluginMeta, state: str, error_msg: str | None = None,
                   error_stack: str | None = None) -> None:
    """按元数据写入/更新插件行（保留用户已修改的 plugin_config）。"""
    with session_scope() as db:
        model = _model_of(meta.type)
        row = db.get(model, meta.plugin_id)
        if model is UiPlugin:
            fields = dict(
                name=meta.name, type=meta.type, version=meta.version, state=state,
                bind_backend_plugin_id=meta.bind_backend_plugin_id, priority=meta.priority,
                dependencies=json.dumps(meta.dependencies, ensure_ascii=False),
                route_path=meta.ui.get("route_path"),
                slots=json.dumps(meta.ui.get("slots") or [], ensure_ascii=False),
                target_slot=meta.ui.get("target_slot"),
                entry_path=meta.ui.get("entry"),
                error_msg=error_msg,
                error_stack=error_stack,
            )
        elif model is ToolConfig:
            fields = dict(
                name=meta.name, type=meta.type, version=meta.version, state=state,
                owner_agent_id=meta.owner_agent_id, bind_ui_plugin_id=meta.bind_ui_plugin_id,
                dependencies=json.dumps(meta.dependencies, ensure_ascii=False),
                error_msg=error_msg,
                error_stack=error_stack,
            )
        else:
            fields = dict(
                name=meta.name, type=meta.type, version=meta.version, state=state,
                bind_ui_plugin_id=meta.bind_ui_plugin_id, priority=meta.priority,
                dependencies=json.dumps(meta.dependencies, ensure_ascii=False),
                private_tool_ids=json.dumps(meta.private_tool_ids, ensure_ascii=False),
                model_params=json.dumps(meta.model_params, ensure_ascii=False),
                error_msg=error_msg,
                error_stack=error_stack,
            )
        if row is None:
            row = model(id=meta.plugin_id, **fields)
            db.add(row)
        else:
            for key, value in fields.items():
                setattr(row, key, value)


def db_update_state(ptype: str, plugin_id: str, state: str,
                    error_msg: str | None = None, keep_error: bool = False,
                    error_stack: str | None = None) -> None:
    """仅更新状态与错误信息。"""
    with session_scope() as db:
        row = db.get(_model_of(ptype), plugin_id)
        if row is None:
            return
        row.state = state
        if error_msg is not None:
            row.error_msg = error_msg
        elif not keep_error:
            row.error_msg = None
        if error_stack is not None:
            row.error_stack = error_stack
        elif not keep_error:
            row.error_stack = None


def db_all_rows() -> list:
    """读取三张插件表全部行（供 reconcile 与 /plugins/list）。"""
    rows: list = []
    with session_scope() as db:
        rows.extend(db.query(AgentPlugin).all())
        rows.extend(db.query(ToolConfig).all())
        rows.extend(db.query(UiPlugin).all())
        for row in rows:
            db.expunge(row)  # 脱离会话，供外部读取
    return rows


def db_plugin_config(ptype: str, plugin_id: str) -> dict:
    with session_scope() as db:
        row = db.get(_model_of(ptype), plugin_id)
        if row is None or not row.plugin_config:
            return {}
        try:
            return json.loads(row.plugin_config)
        except (TypeError, json.JSONDecodeError):
            return {}


def db_set_plugin_config(ptype: str, plugin_id: str, config: dict) -> None:
    with session_scope() as db:
        row = db.get(_model_of(ptype), plugin_id)
        if row is not None:
            row.plugin_config = json.dumps(config, ensure_ascii=False)
