"""内部事件总线（§3.1.5）：业务事件写入 session_event_log 并转发 SSE。

- 所有业务 SSE 事件完整写入 session_event_log（sse:heartbeat 除外）；
- agent:think 流式分片合并落库：SSE 保持逐片实时推送，落库按「任务·智能体·轮次」合并为一条完整记录；
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

# 任务生命周期事件：到达即视为思考流终止，兜底冲刷未收尾缓冲（取消/超时中断场景）
_THINK_TERMINAL_EVENTS = ("task:finish", "task:error", "task:cancelled")


class EventBus:
    """进程内单例事件总线：内部事件 -> 日志落库（think 合并）+ SSE 订阅队列。"""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()
        # (task_id, agent_id) -> 未收尾思考流缓冲，用于整轮合并落库（§8 事件10）
        self._think_buffers: dict[tuple[str, str], dict] = {}

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
            if event_type == "agent:think":
                # 思考分片先进缓冲：整轮结束合并为一条日志，避免逐片碎行
                self._buffer_think(tid, data)
            else:
                # 非 think 事件先冲刷该任务未收尾的思考缓冲，保持时间线顺序
                self._flush_thinks(tid)
                try:
                    self._append_log(tid, event_type, data)
                except Exception:  # 日志落库失败不阻断事件推送
                    _log.exception("session_event_log 写入失败 event_type=%s", event_type)
        # 任务生命周期事件兜底冲刷全部缓冲（流式中断/取消/超时时确保不丢）
        if event_type in _THINK_TERMINAL_EVENTS:
            self._flush_thinks(all_tasks=True)
        if push_sse:
            self._push_sse(event_type, data)

    def publish_heartbeat(self) -> None:
        self.publish("sse:heartbeat", {}, task_id="system", write_log=False)

    def _buffer_think(self, task_id: str, data: dict) -> None:
        """累积 agent:think 流式分片；收到 is_final=True 时把整轮合并写为一条日志。"""
        agent_id = str(data.get("agent_id") or "")
        seq = data.get("seq", 0)
        key = (task_id, agent_id)
        with self._lock:
            buf = self._think_buffers.get(key)
            if buf is None:
                buf = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "content": "",
                    "start_ts": data.get("event_ts"),
                    "last_seq": seq,
                }
                self._think_buffers[key] = buf
            buf["content"] += str(data.get("think_content") or "")
            buf["last_seq"] = seq
            is_final = bool(data.get("is_final"))
        if is_final:
            self._flush_thinks(task_id, agent_id=agent_id)

    def _flush_thinks(self, task_id: str | None = None, agent_id: str | None = None,
                      all_tasks: bool = False) -> None:
        """把思考缓冲合并写入 session_event_log（每条 = 一个智能体的一轮思考）。

        - 默认冲刷指定任务的全部缓冲；
        - agent_id 非空时仅冲刷该智能体（正常收尾路径）；
        - all_tasks=True 用于任务生命周期事件兜底（取消/超时等中断路径）。
        """
        with self._lock:
            if all_tasks:
                keys = list(self._think_buffers.keys())
            elif agent_id is not None:
                keys = [(task_id, agent_id)] if (task_id, agent_id) in self._think_buffers else []
            else:
                keys = [k for k in self._think_buffers if k[0] == task_id]
            buffers = [self._think_buffers.pop(k) for k in keys]
        for buf in buffers:
            try:
                self._append_log(buf["task_id"], "agent:think", {
                    "task_id": buf["task_id"],
                    "agent_id": buf["agent_id"],
                    "seq": buf["last_seq"],
                    "is_final": True,
                    "think_content": buf["content"],
                    "event_ts": buf["start_ts"],
                })
            except Exception:  # 日志落库失败不阻断事件推送
                _log.exception("session_event_log 写入失败 event_type=agent:think")

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
