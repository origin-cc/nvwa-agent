"""内部事件总线（§3.1.5）：业务事件写入 session_event_log 并转发 SSE。

- 所有业务 SSE 事件完整写入 session_event_log（sse:heartbeat 除外）；
- SSE 推送不输出内部堆栈信息（§15）；
- 线程安全：任务 Worker 线程可同步调用 publish。
"""
import asyncio
import json
import threading
import time

from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.taskctx import get_current_task
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import SessionEventLog

_log = get_core_logger()


class EventBus:
    """进程内单例事件总线：内部事件 -> 日志落库 + SSE 订阅队列。"""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """FastAPI 启动时绑定事件循环，用于跨线程投递。"""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(
        self,
        event_type: str,
        payload: dict,
        task_id: str | None = None,
        write_log: bool = True,
        push_sse: bool = True,
    ) -> None:
        """发布事件：payload 自动补充 event_ts；task_id 缺省取当前任务上下文。

        write_log=False 仅用于 sse:heartbeat 等保活事件（§8 事件14）；
        push_sse=False 用于仅补记审计日志（如任务途中插件被禁用，§10 边界处理）。
        """
        data = dict(payload)
        data.setdefault("event_ts", int(time.time() * 1000))
        tid = task_id or get_current_task()
        if write_log:
            try:
                self._append_log(tid, event_type, data)
            except Exception:  # 日志落库失败不阻断事件推送
                _log.exception("session_event_log 写入失败 event_type=%s", event_type)
        if push_sse:
            self._push_sse(event_type, data)

    def publish_heartbeat(self) -> None:
        self.publish("sse:heartbeat", {}, task_id="system", write_log=False)

    def _append_log(self, task_id: str, event_type: str, payload: dict) -> None:
        with session_scope() as db:
            db.add(SessionEventLog(
                task_id=task_id,
                event_type=event_type,
                event_payload=json.dumps(payload, ensure_ascii=False),
            ))

    def _push_sse(self, event_type: str, data: dict) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        text = json.dumps(data, ensure_ascii=False)
        with self._lock:
            queues = list(self._subscribers)
        for q in queues:
            def _put(q=q):
                try:
                    q.put_nowait((event_type, text))
                except asyncio.QueueFull:
                    _log.warning("SSE 订阅队列已满，丢弃事件 %s", event_type)
            try:
                self._loop.call_soon_threadsafe(_put)
            except RuntimeError:
                pass


# 进程级单例
event_bus = EventBus()
