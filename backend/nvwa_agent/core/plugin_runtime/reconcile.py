"""启动恢复与手动重新扫描 reconcile（§3.3 / §3.6）。"""
from datetime import datetime

from sqlalchemy import update

from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.plugin_runtime import runtime_db
from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.core.plugin_runtime.runtime import PluginOpError, get_runtime
from nvwa_agent.core.plugin_runtime.scanner import scan_disk
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import TaskRecord

_log = get_core_logger()


def scan_and_reconcile(initial: bool = False) -> dict:
    """磁盘元数据与数据库记录 reconcile；initial=True 为系统启动恢复。"""
    runtime = get_runtime()
    valid, entries = scan_disk()
    summary = {"scanned": len(valid) + len(entries), "activated": [], "fault": []}

    for entry in entries:
        _handle_invalid_entry(runtime, entry, summary)

    to_activate: list[str] = []
    for meta in valid:
        if _reconcile_meta(runtime, meta, summary):
            to_activate.append(meta.plugin_id)

    _handle_disk_missing(runtime, summary)
    _activate_in_dependency_order(runtime, to_activate)
    runtime.validate_bindings()

    if initial:
        _ensure_orchestrator(runtime)
        _fail_interrupted_tasks()
    _log.info("插件扫描完成: %s", summary)
    return summary


def _ensure_orchestrator(runtime) -> None:
    """核心编排智能体是唯一任务入口：启动恢复时若存在且非 fault，确保其激活。

    - 老库升级（预置快照 count>0 早退、新插件默认 loaded 不激活）时，重启后自动补激活；
    - 仅在 initial=True（系统启动）调用，手动扫描不强制，尊重「可插拔」语义。
    """
    from nvwa_agent.core.plugin_runtime.runtime import ORCHESTRATOR_ID

    meta = runtime.get_meta(ORCHESTRATOR_ID)
    if meta is None or runtime.get_state(ORCHESTRATOR_ID) == "fault":
        return
    if runtime.get_state(ORCHESTRATOR_ID) != "activated":
        try:
            runtime.activate(ORCHESTRATOR_ID)
            _log.info("核心编排智能体（orchestrator-agent）已自动激活")
        except PluginOpError as exc:
            _log.warning("核心编排智能体自动激活失败: %s", exc)


def _handle_invalid_entry(runtime, entry, summary: dict) -> None:
    """三层校验失败 / 缺 plugin.json / ID 冲突条目。"""
    msg = "; ".join(entry.errors)
    stack = "\n".join(entry.errors)
    code = entry.error_code
    pid = entry.plugin_id
    if pid is None:
        _log.warning("插件目录 %s 无效: %s", entry.dir_name, msg)
        return
    row = runtime_db.db_get_row(_row_type(pid), pid)
    if entry.meta is not None:
        # 字段值/交叉引用校验失败或 ID 冲突：有完整 meta，落库 error_stack（§3.4）
        runtime.register_meta(entry.meta, "fault", msg, error_stack=stack)
        if row is None:
            runtime_db.db_upsert_meta(entry.meta, "fault", error_msg=msg, error_stack=stack)
        else:
            runtime_db.db_update_state(entry.meta.type, pid, "fault",
                                       error_msg=msg, error_stack=stack)
    elif runtime.has(pid):
        runtime.mark_fault(pid, code, msg, persist=False, error_stack=stack)
    elif row is not None:
        _register_stub(runtime, row, "fault", f"[{code}] {msg}", error_stack=stack)
    else:
        _log.warning("插件 %s 无效且无法定位记录: %s", pid, msg)
    summary["fault"].append(pid)


def _reconcile_meta(runtime, meta: PluginMeta, summary: dict) -> bool:
    """登记/升级单个有效插件；返回是否需要激活。"""
    pid = meta.plugin_id
    row = runtime_db.db_get_row(meta.type, pid)

    if not runtime.has(pid):
        runtime.register_meta(meta, "loaded")
        if row is None:  # 磁盘新插件：初始 loaded，不自动激活（§3.6.2）
            runtime_db.db_upsert_meta(meta, "loaded")
            if meta.is_backend:
                runtime.load(pid)
            return False
        db_state = row.state
        if db_state == "unloaded":
            runtime._set(pid, "unloaded")
            return False
        if db_state == "fault":
            runtime._set(pid, "fault", row.error_msg)
            return False
        if meta.is_backend:
            runtime.load(pid)
        else:
            runtime._set(pid, db_state)
        return db_state == "activated"

    existing = runtime.get_meta(pid)
    if existing is not None and existing.version == meta.version:
        return runtime.get_state(pid) == "activated"

    # 版本升级（§3.3.4）：注销旧实例 -> 按数据库原状态重新加载
    prev = runtime.get_state(pid)
    _log.info("插件 %s 版本升级 %s -> %s", pid, existing.version if existing else "?", meta.version)
    if prev == "activated":
        try:
            runtime.deactivate(pid)
        except PluginOpError as exc:
            _log.warning("升级前禁用失败 %s: %s", pid, exc)
            runtime._set(pid, "deactivated")
        prev = "activated"
    runtime.drop_instance(pid, run_unload_hook=True)
    runtime.register_meta(meta, "loaded")
    restore = prev if prev in ("loaded", "deactivated", "activated") else "loaded"
    runtime_db.db_upsert_meta(meta, restore)
    if meta.is_backend and restore != "loaded":
        runtime._set(pid, "loaded")
    if meta.is_backend:
        runtime.load(pid)
    return restore == "activated"


def _handle_disk_missing(runtime, summary: dict) -> None:
    """数据库有记录但磁盘缺失 -> 内存 fault，不修改数据库（§11 场景1）。"""
    for row in runtime_db.db_all_rows():
        if runtime.has(row.id) or row.state in ("unloaded", "fault"):
            continue
        _register_stub(runtime, row, "fault", "磁盘插件文件缺失或损坏")
        runtime.mark_fault(row.id, "PLUGIN_SCHEMA_INVALID", "磁盘插件文件缺失或损坏",
                           persist=False, notify=True)
        summary["fault"].append(row.id)


def _register_stub(runtime, row, state: str, error: str,
                   error_stack: str | None = None) -> None:
    """由数据库行构造内存元数据存根（磁盘文件不可用时）。"""
    meta = PluginMeta(
        plugin_id=row.id, name=row.name, version=row.version or "0.0.0", type=row.type,
        dir_path=None,
    )
    meta.owner_agent_id = getattr(row, "owner_agent_id", None)
    meta.bind_ui_plugin_id = getattr(row, "bind_ui_plugin_id", None)
    meta.bind_backend_plugin_id = getattr(row, "bind_backend_plugin_id", None)
    runtime.register_meta(meta, state, error, error_stack=error_stack)


def _row_type(pid: str) -> str:
    for ptype in ("backend_agent", "backend_tool", "ui_page_plugin"):
        if runtime_db.db_get_row(ptype, pid) is not None:
            return ptype
    return "backend_agent"


def _activate_in_dependency_order(runtime, to_activate: list[str]) -> None:
    """依赖拓扑序激活：多轮推进直至稳定；无法满足则置 fault。"""
    for _ in range(len(to_activate) + 1):
        pending = [pid for pid in to_activate
                   if runtime.get_state(pid) not in ("activated", "fault")]
        if not pending:
            return
        progressed = False
        for pid in pending:
            meta = runtime.get_meta(pid)
            if meta and all(runtime.get_state(d) == "activated" for d in meta.dependencies):
                try:
                    runtime.activate(pid)
                    progressed = True
                except PluginOpError as exc:
                    _log.warning("插件 %s 激活失败: %s", pid, exc)
        if not progressed:
            for pid in pending:
                runtime.mark_fault(pid, "PLUGIN_DEPENDENCY_MISSING",
                                   "依赖无法满足（缺失/循环/未激活）")
            return


def _fail_interrupted_tasks() -> None:
    """重启前 pending/running 任务统一置 failed（§3.6.3）。"""
    with session_scope() as db:
        result = db.execute(
            update(TaskRecord)
            .where(TaskRecord.status.in_(["pending", "running"]))
            .values(status="failed", error_msg="服务重启，任务中断",
                    finished_at=datetime.now())
        )
        if result.rowcount:
            _log.info("服务重启：%d 个未完成任务已置为 failed", result.rowcount)
