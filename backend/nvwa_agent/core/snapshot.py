"""快照核心（§7.4/§7.4.1）：save 采集 / load 全量覆盖 / 导入导出 / 预置快照。

- snapshot_json 只存 plugin_id、enabled、config；不含 system_config
- load 全量覆盖语义：enabled=true→activated、false→deactivated；
  不在快照内的插件一律 deactivated（PRD 3.5.2）
- 导入缺失插件：告警跳过，不阻断（§11 场景3）
"""
import json
from datetime import datetime, timezone

from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.plugin_runtime import get_runtime
from nvwa_agent.database import session_scope
from nvwa_agent.models.misc import AgentProfile

_log = get_core_logger()

_SNAPSHOT_VERSION = "0.1-alpha"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- 保存 ----------------
def build_snapshot_json(name: str, is_preset: bool = False) -> dict:
    """采集当前全部插件的 启用状态 + config。"""
    plugins = {"backend_agents": [], "backend_tools": [], "ui_plugins": []}
    for item in get_runtime().list_plugins():
        entry = {
            "plugin_id": item["plugin_id"],
            "enabled": item["state"] == "activated",
            "config": item.get("plugin_config") or {},
        }
        kind = {"backend_agent": "backend_agents", "backend_tool": "backend_tools"}.get(
            item["type"], "ui_plugins")
        plugins[kind].append(entry)
    return {
        "snapshot_meta": {"name": name, "version": _SNAPSHOT_VERSION,
                          "created_at": _now_iso(), "is_preset": bool(is_preset)},
        "plugins": plugins,
    }


def save_snapshot(name: str, is_preset: bool = False) -> int:
    snapshot = build_snapshot_json(name, is_preset)
    with session_scope() as db:
        row = AgentProfile(name=name, is_preset=int(is_preset),
                           snapshot_json=json.dumps(snapshot, ensure_ascii=False))
        db.add(row)
        db.flush()
        snapshot_id = row.id
    _log.info("快照已保存 id=%s name=%s", snapshot_id, name)
    return snapshot_id


# ---------------- 加载（全量覆盖） ----------------
def load_snapshot(snapshot_id: int) -> dict:
    """加载快照并立即应用：返回 {applied, deactivated, missing_plugin_ids, warnings}。"""
    with session_scope() as db:
        row = db.get(AgentProfile, snapshot_id)
        if row is None:
            raise KeyError(f"快照 {snapshot_id} 不存在")
        snapshot = json.loads(row.snapshot_json)
    return apply_snapshot(snapshot)


def apply_snapshot(snapshot: dict) -> dict:
    """按快照全量覆盖当前插件状态（导入与加载共用，§11 场景3）。"""
    runtime = get_runtime()
    entries = {}
    for kind in ("backend_agents", "backend_tools", "ui_plugins"):
        for entry in (snapshot.get("plugins") or {}).get(kind, []):
            entries[entry["plugin_id"]] = entry

    existing = {p["plugin_id"] for p in runtime.list_plugins()}
    missing = sorted(pid for pid in entries if pid not in existing)
    warnings = []
    if missing:
        warnings.append(f"以下插件本机不存在，已跳过：{', '.join(missing)}")

    applied, deactivated = [], []
    for pid, entry in entries.items():
        if pid in missing:
            continue
        target = "activated" if entry.get("enabled", False) else "deactivated"
        if _transition(runtime, pid, target):
            (applied if target == "activated" else deactivated).append(pid)
    # 全量覆盖：不在快照内且当前激活的插件一律禁用
    for pid in sorted(existing - set(entries)):
        if _transition(runtime, pid, "deactivated"):
            deactivated.append(pid)

    if warnings:
        for w in warnings:
            _log.warning("快照应用告警: %s", w)
    _log.info("快照应用完成 activated=%d deactivated=%d missing=%d",
              len(applied), len(deactivated), len(missing))
    return {"applied": applied, "deactivated": deactivated,
            "missing_plugin_ids": missing, "warnings": warnings}


def _transition(runtime, pid: str, target: str) -> bool:
    """执行状态迁移；失败记录告警不阻断。"""
    try:
        current = runtime.get_state(pid)
        if target == "activated" and current != "activated":
            runtime.activate(pid)
            return True
        if target == "deactivated" and current == "activated":
            runtime.deactivate(pid)
            return True
    except Exception as exc:
        _log.warning("快照状态迁移失败 %s -> %s: %s", pid, target, exc)
    return False


# ---------------- 导入 ----------------
def import_snapshot(name: str, snapshot: dict) -> dict:
    """导入快照JSON：保存为新记录并立即应用（缺失插件告警跳过）。"""
    snapshot["snapshot_meta"] = {**(snapshot.get("snapshot_meta") or {}),
                                 "name": name, "created_at": _now_iso(),
                                 "version": _SNAPSHOT_VERSION, "is_preset": False}
    with session_scope() as db:
        row = AgentProfile(name=name, is_preset=0,
                           snapshot_json=json.dumps(snapshot, ensure_ascii=False))
        db.add(row)
        db.flush()
        snapshot_id = row.id
    result = apply_snapshot(snapshot)
    result["snapshot_id"] = snapshot_id
    result["warning"] = "; ".join(result["warnings"]) or None
    return result


# ---------------- 预置快照（首次启动） ----------------
def ensure_preset_snapshots() -> None:
    """预置两个示例快照（§7.4）：纯对话模式 / 知识库增强模式。"""
    with session_scope() as db:
        if db.query(AgentProfile).count() > 0:
            return
    presets = [
        ("预置·纯对话模式", ["demo-agent-plugin", "demo-file-tool",
                             "demo-ui-chat", "demo-ui-think-visualizer"]),
        ("预置·知识库增强模式", None),  # None = 当前全部插件
    ]
    for name, only_ids in presets:
        snapshot = build_snapshot_json(name, is_preset=True)
        if only_ids is not None:
            for kind in snapshot["plugins"]:
                snapshot["plugins"][kind] = [
                    e for e in snapshot["plugins"][kind] if e["plugin_id"] in only_ids]
        with session_scope() as db:
            db.add(AgentProfile(name=name, is_preset=1,
                                snapshot_json=json.dumps(snapshot, ensure_ascii=False)))
    _log.info("预置示例快照已初始化（2 个）")


def list_snapshots() -> list[dict]:
    with session_scope() as db:
        rows = db.query(AgentProfile).order_by(AgentProfile.id).all()
        return [
            {"snapshot_id": r.id, "name": r.name, "is_preset": bool(r.is_preset),
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]
