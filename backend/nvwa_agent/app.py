"""FastAPI 应用工厂与启动生命周期。

启动顺序（§3.6）：日志 -> 建表 -> 默认配置 -> 目录 -> 插件扫描恢复
-> 重启任务置 failed（reconcile 内）-> SSE 心跳。
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nvwa_agent.config import get, init_defaults
from nvwa_agent.core.log import get_core_logger, setup_logging
from nvwa_agent.core.paths import resolve_path
from nvwa_agent.core.plugin_runtime import event_bus, scan_and_reconcile
from nvwa_agent.database import init_db


def ensure_runtime_dirs() -> None:
    """目录规范落地（§13）：data/{uploads,generated_docs,faiss_index,logs} 与 plugins/。"""
    data_base = resolve_path(get("data_dir", "./data"))
    for sub in ("uploads", "generated_docs", "faiss_index", "logs"):
        (data_base / sub).mkdir(parents=True, exist_ok=True)
    resolve_path(get("plugins_dir", "./plugins")).mkdir(parents=True, exist_ok=True)


async def _heartbeat_loop() -> None:
    """SSE 心跳定时器：默认 30 秒（§8 事件14，不写入 session_event_log）。"""
    while True:
        await asyncio.sleep(30)
        event_bus.publish_heartbeat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log = get_core_logger()
    init_db()
    init_defaults()
    ensure_runtime_dirs()
    event_bus.bind_loop(asyncio.get_running_loop())

    import threading
    threading.Thread(target=scan_and_reconcile, kwargs={"initial": True},
                     daemon=True, name="nvwa-plugin-recover").start()

    from nvwa_agent.core.scheduler import start_worker
    start_worker()

    heartbeat = asyncio.create_task(_heartbeat_loop())
    log.info("NvwaAgent 后端启动完成（v0.1-alpha）")
    try:
        yield
    finally:
        heartbeat.cancel()
        log.info("NvwaAgent 后端关闭")


def create_app() -> FastAPI:
    app = FastAPI(title="NvwaAgent", version="0.1.0", lifespan=lifespan)
    from nvwa_agent.server.errors import register_error_handlers
    from nvwa_agent.server.routes import register_routes

    register_error_handlers(app)
    register_routes(app)
    return app
