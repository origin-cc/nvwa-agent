"""后台FIFO串行任务队列Worker（§10 任务队列与执行模型）。

- 同一时刻仅1个任务running；排队任务由前端经 REST 查询展示等待状态；
- 兜底：单任务最大执行时长（超时线程标记失败，执行线程安全退出）；
- 任务途中插件被禁用：任务继续执行完毕，事后补记审计日志（§10 边界处理）。
"""
import json
import queue as _queue
import threading
from datetime import datetime

from nvwa_agent.config import get_task_limits
from nvwa_agent.core import taskctx
from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.plugin_runtime.event_bus import event_bus
from nvwa_agent.core.plugin_runtime.runtime import (
    ToolCallLimitExceeded,
    get_runtime,
)
from nvwa_agent.core.scheduler import intent as intent_mod
from nvwa_agent.core.scheduler.agent_runner import run_agent_graph
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import Conversation, TaskRecord

_log = get_core_logger()

_task_queue: "_queue.Queue[str]" = _queue.Queue()
_started = False


def enqueue(task_id: str) -> None:
    _task_queue.put(task_id)


def start_worker() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_worker_loop, daemon=True, name="nvwa-task-worker").start()
    _log.info("任务队列Worker已启动（FIFO串行）")


def _worker_loop() -> None:
    while True:
        task_id = _task_queue.get()
        try:
            _run_task(task_id)
        except Exception:
            _log.exception("任务 %s 执行异常", task_id)
        finally:
            _task_queue.task_done()


def _run_task(task_id: str) -> None:
    runtime = get_runtime()
    task = _load_task(task_id)
    if task is None or task.status != "pending":
        return

    prompt = task.input_prompt or ""
    file_ids = json.loads(task.file_ids) if task.file_ids else []
    max_duration, _ = get_task_limits()
    taskctx.set_current_task(task_id)
    runtime.reset_tool_counter(task_id)
    _set_task(task_id, status="running")
    event_bus.publish("task:start", {"task_id": task_id}, task_id=task_id)

    involved_states = _snapshot_plugin_states()
    answer: str | None = None
    error_code, error_msg = None, None

    def _execute() -> None:
        nonlocal answer, error_code, error_msg
        try:
            event_bus.publish("task:update", {
                "task_id": task_id, "status": "running", "step_desc": "意图识别中",
            }, task_id=task_id)
            agents = runtime.activated_agents()
            if not agents:
                error_code, error_msg = "NO_AGENT_MATCHED", "当前无已启用的Agent插件"
                return
            result = intent_mod.recognize(prompt, agents)
            picked = intent_mod.pick_agent(result)
            if picked is None:
                error_code, error_msg = "NO_AGENT_MATCHED", "未匹配到任何可用Agent"
                return
            meta, instance, graph = picked
            with session_scope() as db:
                row = db.get(TaskRecord, task_id)
                if row is not None:
                    row.active_agent_ids = json.dumps([meta.plugin_id])
            answer = run_agent_graph(meta, instance, graph, prompt, task_id, file_ids)
        except ToolCallLimitExceeded as exc:
            error_code, error_msg = "TASK_TOOL_CALL_LIMIT", str(exc)
        except Exception as exc:  # LLM推理失败等（§11 场景4）
            _log.exception("任务 %s 执行失败", task_id)
            error_code, error_msg = "LLM_INFER_FAILED", "模型推理失败，请稍后重试"

    exec_thread = threading.Thread(target=_execute, daemon=True, name=f"task-{task_id[:8]}")
    exec_thread.start()
    exec_thread.join(timeout=max_duration)

    timed_out = exec_thread.is_alive()
    if timed_out:
        error_code, error_msg = "TASK_TIMEOUT", f"任务超过最大执行时长 {max_duration}s，已终止"

    if error_code is not None:
        event_bus.publish("task:error", {
            "task_id": task_id, "error_msg": error_msg, "error_code": error_code,
        }, task_id=task_id)
        _set_task(task_id, status="failed", error_msg=error_msg)
    else:
        result_text = answer or ""
        event_bus.publish("task:finish", {
            "task_id": task_id, "result": result_text,
        }, task_id=task_id)
        _set_task(task_id, status="finish", result=result_text)

    _log_mitask_plugin_changes(task_id, involved_states)
    runtime.reset_tool_counter(task_id)
    taskctx.clear_current_task()


def _load_task(task_id: str):
    with session_scope() as db:
        return db.get(TaskRecord, task_id)


def _set_task(task_id: str, **fields) -> None:
    with session_scope() as db:
        row = db.get(TaskRecord, task_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        if fields.get("status") in ("finish", "failed"):
            row.finished_at = datetime.now()
        conv = db.get(Conversation, row.conversation_id)
        if conv is not None:
            conv.updated_at = datetime.now()


def _snapshot_plugin_states() -> dict[str, str]:
    runtime = get_runtime()
    return {pid: runtime.get_state(pid) for pid in runtime.all_ids()}


def _log_mitask_plugin_changes(task_id: str, before: dict[str, str]) -> None:
    """任务执行期间被禁用/卸载的插件补记审计日志（§10 边界处理，§11 场景6）。"""
    runtime = get_runtime()
    for pid, prev in before.items():
        current = runtime.get_state(pid)
        if prev == "activated" and current in ("deactivated", "unloaded", "fault"):
            event_bus.publish("plugin:deactivated", {
                "plugin_id": pid,
                "note": "任务执行期间插件被禁用/卸载，任务继续执行完毕",
            }, task_id=task_id, push_sse=False)
