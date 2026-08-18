"""pytest 全局夹具：临时 SQLite 数据库 + mock 推理后端隔离。

- 所有测试使用 tmp_path 下的独立数据库，不触碰仓库 data/nvwa_agent.db；
- 默认强制 llm_provider=mock，任何测试不发起真实网络请求。
"""
import pytest

import nvwa_agent.database as database


@pytest.fixture(scope="session", autouse=True)
def isolated_db(tmp_path_factory):
    """整个测试会话使用独立的临时数据库。"""
    db_file = tmp_path_factory.mktemp("nvwa-db") / "test_nvwa_agent.db"
    database.DB_PATH = db_file
    database._engine = None
    database._SessionLocal = None
    database.init_db()
    from nvwa_agent.config import init_defaults, set_many

    init_defaults()
    set_many({"llm_provider": "mock", "mock_mode_enabled": False})
    yield db_file
    if database._engine is not None:
        database._engine.dispose()
        database._engine = None
        database._SessionLocal = None
