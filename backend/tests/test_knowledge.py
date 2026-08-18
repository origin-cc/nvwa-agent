"""M16 知识库解析/切片/向量索引测试（v1.0 §10）。"""
import numpy as np
import pytest

from nvwa_agent.core.knowledge.parser import ParseError, chunk_text, extract_text


# ---------------- parser（纯函数，mock 模式可测） ----------------
def test_extract_text_txt(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    assert extract_text(str(f), ".txt") == "hello world"


def test_extract_text_unsupported_suffix():
    with pytest.raises(ParseError):
        extract_text("x.docx", ".docx")


def test_extract_text_missing_file():
    with pytest.raises(ParseError):
        extract_text("no-such-file.txt", ".txt")


def test_chunk_text_basic():
    text = "a" * 50 + "b" * 50  # 100 字符
    chunks = chunk_text(text, size=50, overlap=0)
    assert chunks == ["a" * 50, "b" * 50]


def test_chunk_text_empty():
    assert chunk_text("   ") == []


def test_chunk_text_overlap():
    chunks = chunk_text("abcdefghij", size=6, overlap=2)
    assert chunks == ["abcdef", "efghij"]


# ---------------- vector_store（FAISS，纯本地） ----------------
def test_vector_store_add_search_rebuild(monkeypatch, tmp_path):
    from nvwa_agent.core.knowledge.vector_store import VectorStore

    monkeypatch.setattr(
        "nvwa_agent.core.knowledge.vector_store.get_config",
        lambda k, d=None: str(tmp_path) if k == "data_dir" else d,
    )
    store = VectorStore()
    vectors = np.random.rand(5, 8).astype("float32")
    ids = store.add(vectors)
    assert ids == [0, 1, 2, 3, 4]
    assert store.total == 5

    query = np.random.rand(8).astype("float32")
    results = store.search(query, top_k=3)
    assert len(results) == 3

    store.rebuild(np.empty((0, 8), dtype="float32"))
    assert store.total == 0


# ---------------- service（失败分支，不依赖真实 embedding） ----------------
def test_knowledge_service_delete_missing():
    from nvwa_agent.core.knowledge.service import KnowledgeService

    assert KnowledgeService().delete_doc("no-such-doc") is False


def test_knowledge_service_rebuild_empty(monkeypatch, tmp_path):
    from nvwa_agent.core.knowledge.service import KnowledgeService

    monkeypatch.setattr(
        "nvwa_agent.core.knowledge.vector_store.get_config",
        lambda k, d=None: str(tmp_path) if k == "data_dir" else d,
    )
    assert KnowledgeService().rebuild_index() == 0  # 无 chunks → 不调 embedding


def test_knowledge_service_search_empty_query():
    from nvwa_agent.core.knowledge.service import KnowledgeService

    assert KnowledgeService().search("   ") == []
