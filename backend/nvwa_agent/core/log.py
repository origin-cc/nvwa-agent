"""日志框架（§15）：core / backend_plugin / frontend-proxy 三类日志。

- 单文件最大 100MB，保留最近 5 份（按大小轮转）；
- ERROR 级别日志记录完整堆栈（调用方使用 logger.exception / exc_info=True）；
- SSE 向外推送事件不输出内部堆栈。
"""
import logging
from logging.handlers import RotatingFileHandler

from nvwa_agent.core.paths import REPO_ROOT

LOG_DIR = REPO_ROOT / "data" / "logs"
_MAX_BYTES = 100 * 1024 * 1024
_BACKUP_COUNT = 5

# 分类 -> (logger名, 文件名)
_CATEGORIES = {
    "core": ("nvwa.core", "core.log"),
    "backend_plugin": ("nvwa.plugin", "backend_plugin.log"),
    "frontend-proxy": ("nvwa.frontend", "frontend-proxy.log"),
}

_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_configured = False


def setup_logging() -> None:
    """初始化三类日志（幂等）。"""
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FMT))
    for _cat, (name, filename) in _CATEGORIES.items():
        logger = logging.getLogger(name)
        handler = RotatingFileHandler(
            LOG_DIR / filename, maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FMT))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False
        if name == "nvwa.core":  # 基座日志同步输出到控制台，便于开发观察
            logger.addHandler(console)
    _configured = True


def get_core_logger() -> logging.Logger:
    setup_logging()
    return logging.getLogger("nvwa.core")


def get_plugin_logger() -> logging.Logger:
    """后端插件日志（每条日志由 PluginLogger 携带 plugin_id 前缀）。"""
    setup_logging()
    return logging.getLogger("nvwa.plugin")


def get_frontend_logger() -> logging.Logger:
    """前端 UI 插件异常上报日志。"""
    setup_logging()
    return logging.getLogger("nvwa.frontend")
