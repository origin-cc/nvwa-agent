"""任务执行上下文：工作线程与插件服务共享当前 task_id。

session_event_log 写入与 agent:think / tool:* 事件均依赖此上下文；
无任务运行时取值 "system"（插件生命周期等非任务事件）。
"""
from contextvars import ContextVar

_current_task_id: ContextVar[str] = ContextVar("nvwa_task_id", default="system")


def set_current_task(task_id: str) -> None:
    _current_task_id.set(task_id)


def get_current_task() -> str:
    return _current_task_id.get()


def clear_current_task() -> None:
    _current_task_id.set("system")
