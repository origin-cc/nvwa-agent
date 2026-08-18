"""插件管理 API（§9 插件管理）：list/scan/activate/deactivate/unload/config/state/static/ui-error/logs。"""
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from nvwa_agent.config import get as get_config
from nvwa_agent.core.log import get_frontend_logger
from nvwa_agent.core.paths import resolve_path
from nvwa_agent.core.plugin_runtime import get_runtime, scan_and_reconcile
from nvwa_agent.core.plugin_runtime import runtime_db
from nvwa_agent.database import get_db, session_scope
from nvwa_agent.models.misc import UiPluginState
from nvwa_agent.server.errors import ApiError

router = APIRouter(tags=["插件管理"])
_frontend_log = get_frontend_logger()

_MIME = {
    ".js": "text/javascript", ".mjs": "text/javascript",
    ".css": "text/css", ".html": "text/html", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".woff": "font/woff", ".woff2": "font/woff2",
}


class PluginConfigBody(BaseModel):
    config: dict


class UiStateBody(BaseModel):
    state: dict


class UiErrorBody(BaseModel):
    error_msg: str
    stack: str | None = None


@router.get("/api/v1/plugins/list")
def list_plugins():
    return {"plugins": get_runtime().list_plugins()}


@router.post("/api/v1/plugins/scan")
def scan_plugins():
    summary = scan_and_reconcile(initial=False)
    return summary


@router.post("/api/v1/plugins/{plugin_id}/activate")
def activate_plugin(plugin_id: str):
    get_runtime().activate(plugin_id)
    return {"plugin_id": plugin_id, "state": get_runtime().get_state(plugin_id)}


@router.post("/api/v1/plugins/{plugin_id}/deactivate")
def deactivate_plugin(plugin_id: str):
    get_runtime().deactivate(plugin_id)
    return {"plugin_id": plugin_id, "state": get_runtime().get_state(plugin_id)}


@router.post("/api/v1/plugins/{plugin_id}/unload")
def unload_plugin(plugin_id: str):
    get_runtime().unload(plugin_id)
    return {"plugin_id": plugin_id, "state": get_runtime().get_state(plugin_id)}


@router.put("/api/v1/plugins/{plugin_id}/config")
def update_plugin_config(plugin_id: str, body: PluginConfigBody):
    runtime = get_runtime()
    meta = runtime.get_meta(plugin_id)
    if meta is None:
        raise ApiError("NOT_FOUND", f"插件 {plugin_id} 不存在")
    runtime_db.db_set_plugin_config(meta.type, plugin_id, body.config)
    ctx = runtime.get_ctx(plugin_id)  # 同步更新已加载实例的运行时配置
    if ctx is not None:
        ctx.config = {**meta.config, **body.config}
    return {"plugin_id": plugin_id, "config": body.config}


@router.get("/api/v1/plugins/{plugin_id}/state")
def get_ui_state(plugin_id: str, db=Depends(get_db)):
    row = db.get(UiPluginState, plugin_id)
    if row is None:
        return {"plugin_id": plugin_id, "state": {}}
    try:
        state = json.loads(row.state_json)
    except (TypeError, ValueError):
        state = {}
    return {"plugin_id": plugin_id, "state": state}


@router.put("/api/v1/plugins/{plugin_id}/state")
def put_ui_state(plugin_id: str, body: UiStateBody):
    with session_scope() as db:
        row = db.get(UiPluginState, plugin_id)
        serialized = json.dumps(body.state, ensure_ascii=False)
        if row is None:
            db.add(UiPluginState(plugin_id=plugin_id, state_json=serialized))
        else:
            row.state_json = serialized
    return {"plugin_id": plugin_id, "saved": True}


@router.post("/api/v1/plugins/{plugin_id}/ui-error")
def report_ui_error(plugin_id: str, body: UiErrorBody):
    """前端 ErrorBoundary 捕获的 UI 插件渲染异常上报（§11 场景5）。"""
    _frontend_log.error("[plugin:%s] %s\nstack: %s",
                        plugin_id, body.error_msg, body.stack or "(无堆栈)")
    return {"received": True}


@router.get("/api/v1/plugins/static/{plugin_id}/{file_path:path}")
def plugin_static(plugin_id: str, file_path: str):
    """UI插件静态资源只读访问：仅允许访问该插件目录内文件，防路径穿越（§9.9）。"""
    plugins_root = resolve_path(get_config("plugins_dir", "./plugins"))
    base = (plugins_root / plugin_id).resolve()
    target = (base / file_path).resolve()
    if base not in target.parents and target != base:
        raise ApiError("NOT_FOUND", "非法的静态资源路径")
    if not target.is_file():
        raise ApiError("NOT_FOUND", f"静态资源不存在: {file_path}")
    media_type = _MIME.get(target.suffix.lower(), "application/octet-stream")
    # 开发期插件文件可能随时修改：禁用启发式缓存，强制浏览器每次回源验证
    return FileResponse(target, media_type=media_type, headers={"Cache-Control": "no-cache"})


_LOG_LINE_RE = re.compile(r"^(\S+ \S+) (\w+) \[(\S+)\] \[([^\]]+)\] (.*)$")


@router.get("/api/v1/plugins/{plugin_id}/logs")
def get_plugin_logs(
    plugin_id: str,
    level: str | None = Query(None),
    keyword: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """查询插件运行日志（只读 backend_plugin.log，按 plugin_id/级别/关键字过滤，§6.4）。"""
    from nvwa_agent.core.log import LOG_DIR

    log_file = LOG_DIR / "backend_plugin.log"
    if not log_file.is_file():
        return {"plugin_id": plugin_id, "logs": []}

    marker = f"[{plugin_id}]"
    matched: list[dict] = []
    # 从文件尾部读取，避免一次性加载过大（§6.4）
    with log_file.open("r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 10 * 1024 * 1024))
        for line in f.read().splitlines():
            if marker not in line:
                continue
            m = _LOG_LINE_RE.match(line)
            if not m:
                continue
            time_s, lvl, _logger, _pid, msg = m.groups()
            if level and lvl.upper() != level.upper():
                continue
            if keyword and keyword not in msg:
                continue
            matched.append({"time": time_s, "level": lvl, "message": msg})
    return {"plugin_id": plugin_id, "logs": matched[-limit:]}
