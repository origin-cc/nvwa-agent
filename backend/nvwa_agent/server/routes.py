"""路由注册汇总（M2 完成：配置/插件/会话/任务/文件/SSE；快照 M7、知识库 M6 接入）。"""
from fastapi import FastAPI

from nvwa_agent.server.routers import (
    conversation,
    files,
    plugins,
    system_config,
    task,
)
from nvwa_agent.server import sse

_ALL_ROUTERS = (
    system_config.router,
    plugins.router,
    conversation.router,
    task.router,
    files.router,
    sse.router,
)


def register_routes(app: FastAPI) -> None:
    for router in _ALL_ROUTERS:
        app.include_router(router)
