"""SQLite 数据库：引擎、会话、自动建表与 schema 版本检查（§7.13）。

- 数据库文件：{data_dir}/nvwa_agent.db（默认 ./data/nvwa_agent.db）
- v0.1-alpha 不实现自动迁移：版本不匹配时提示用户备份数据库
"""
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.paths import REPO_ROOT

SCHEMA_VERSION = 1
DB_PATH = REPO_ROOT / "data" / "nvwa_agent.db"

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    """全部 ORM 模型的声明基类。"""


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _enable_foreign_keys(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # SQLite 需显式开启级联删除
            cursor.close()

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    """启动自动建表 + schema 版本检查。"""
    from nvwa_agent import models  # noqa: F401  确保所有模型完成注册

    engine = get_engine()
    Base.metadata.create_all(engine)
    _check_schema_version(engine)


def _check_schema_version(engine) -> None:
    log = get_core_logger()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT value FROM system_config WHERE key='schema_version'")
        ).mappings().first()
        if row is None:
            conn.execute(
                text("INSERT INTO system_config(key, value, description) "
                     "VALUES('schema_version', :v, '数据库schema版本(系统内部)')"),
                {"v": str(SCHEMA_VERSION)},
            )
            conn.commit()
            log.info("数据库初始化 schema_version=%s", SCHEMA_VERSION)
        elif str(row["value"]).strip('"') != str(SCHEMA_VERSION):
            log.warning(
                "数据库schema版本不匹配（当前=%s，程序=%s）：请先备份 %s 后再继续，"
                "v0.1-alpha 不支持自动迁移", row["value"], SCHEMA_VERSION, DB_PATH,
            )


def get_db():
    """FastAPI 依赖：请求级会话（由路由显式 commit）。"""
    get_engine()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """线程/后台任务使用的短会话上下文：自动 commit/rollback/close。"""
    get_engine()
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def utcnow() -> datetime:
    """统一的当前时间（本地时区，单机部署）。"""
    return datetime.now()
