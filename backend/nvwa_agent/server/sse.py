"""SSE 订阅端点（§8）：/api/v1/sse/subscribe，事件格式 event:name + data:JSON。"""
import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from nvwa_agent.core.plugin_runtime.event_bus import event_bus

router = APIRouter(tags=["SSE"])


@router.get("/api/v1/sse/subscribe")
async def subscribe():
    queue = event_bus.subscribe()

    async def event_stream():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    # 25s 无事件输出注释行保活；业务心跳 sse:heartbeat 30s 周期推送
                    event_type, text = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: {event_type}\ndata: {text}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
