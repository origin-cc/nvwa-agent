"""M16 reconcile 恢复流程测试（v1.0 §10.1 运行时状态机）。"""
from nvwa_agent.core.plugin_runtime import runtime_db
from nvwa_agent.core.plugin_runtime.meta import PluginMeta
from nvwa_agent.core.plugin_runtime.reconcile import (
    _activate_in_dependency_order,
    _fail_interrupted_tasks,
    _reconcile_meta,
)
from nvwa_agent.core.plugin_runtime.runtime import get_runtime
from nvwa_agent.database import session_scope
from nvwa_agent.models.plugin import AgentPlugin
from nvwa_agent.models.task import Conversation, TaskRecord


def _meta(pid, version="1.0.0", ptype="backend_agent"):
    return PluginMeta(plugin_id=pid, name=pid, version=version, type=ptype)


def test_reconcile_db_unloaded_restore():
    runtime = get_runtime()
    meta = _meta("rec-unloaded")
    runtime_db.db_upsert_meta(meta, "unloaded")
    assert _reconcile_meta(runtime, meta, {}) is False
    assert runtime.get_state("rec-unloaded") == "unloaded"


def test_reconcile_db_fault_restore():
    runtime = get_runtime()
    meta = _meta("rec-fault")
    runtime_db.db_upsert_meta(meta, "fault", error_msg="测试故障")
    assert _reconcile_meta(runtime, meta, {}) is False
    assert runtime.get_state("rec-fault") == "fault"


def test_reconcile_version_upgrade_reloads():
    runtime = get_runtime()
    meta = _meta("rec-upgrade", version="1.0.0")
    # 先登记旧版本，再以新版本 reconcile（backend 无文件，load 失败进 fault）
    runtime.register_meta(meta, "loaded")
    runtime_db.db_upsert_meta(meta, "loaded")
    new_meta = _meta("rec-upgrade", version="2.0.0")
    result = _reconcile_meta(runtime, new_meta, {})
    # 升级后 load 因缺文件失败，最终非 activated
    assert result is False
    assert runtime.get_state("rec-upgrade") in ("loaded", "fault")


def test_activate_in_dependency_order_missing_dep_marks_fault():
    runtime = get_runtime()
    child = _meta("rec-child")
    child.dependencies = ["no-such-dep"]
    runtime.register_meta(child, "loaded")
    _activate_in_dependency_order(runtime, ["rec-child"])
    assert runtime.get_state("rec-child") == "fault"


def test_fail_interrupted_tasks():
    with session_scope() as db:
        db.add(Conversation(conversation_id="rec-conv", title="t"))
        db.add(TaskRecord(task_id="rec-task", conversation_id="rec-conv", status="pending"))
    _fail_interrupted_tasks()
    with session_scope() as db:
        assert db.get(TaskRecord, "rec-task").status == "failed"
