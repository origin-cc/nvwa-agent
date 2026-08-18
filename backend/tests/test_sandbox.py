"""M10 工具沙箱精细化权限单元测试（v1.0 §4 FileAccessor）。"""
import pytest

from nvwa_agent.core.plugin_runtime.services import FileAccessorImpl
from nvwa_agent.sdk.context import FilePermissionError


def _setup_whitelist(monkeypatch, tmp_path):
    """构造临时白名单目录并 mock get_config。"""
    uploads = tmp_path / "uploads"
    docs = tmp_path / "generated_docs"
    uploads.mkdir()
    docs.mkdir()
    monkeypatch.setattr(
        "nvwa_agent.core.plugin_runtime.services.get_config",
        lambda key, default=None: (
            [str(uploads), str(docs)] if key == "file_access_whitelist_dirs" else default
        ),
    )
    return uploads, docs


# ---------------- 未声明 file_permissions：继承全局白名单（§4.3 第2条） ----------------
def test_no_permissions_read_write_within_whitelist(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1")
    (uploads / "a.txt").write_text("hi")
    assert fs.read_text(str(uploads / "a.txt")) == "hi"
    fs.write_text(str(uploads / "b.txt"), "x")
    assert (uploads / "b.txt").read_text() == "x"


def test_no_permissions_reject_outside_whitelist(monkeypatch, tmp_path):
    _setup_whitelist(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    fs = FileAccessorImpl("p1")
    with pytest.raises(FilePermissionError):
        fs.read_text(str(outside / "x.txt"))


# ---------------- 声明 file_permissions：按操作精细化（§4.3 第3条） ----------------
def test_read_within_declared_read_dirs(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1", {"read_dirs": [str(uploads)], "write_dirs": [str(docs)]})
    (uploads / "a.txt").write_text("hi")
    assert fs.read_text(str(uploads / "a.txt")) == "hi"


def test_read_outside_declared_read_dirs(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1", {"read_dirs": [str(uploads)], "write_dirs": [str(docs)]})
    (docs / "a.txt").write_text("hi")
    with pytest.raises(FilePermissionError):
        fs.read_text(str(docs / "a.txt"))  # docs 在 write_dirs 不在 read_dirs


def test_write_within_declared_write_dirs(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1", {"write_dirs": [str(docs)]})
    fs.write_text(str(docs / "a.txt"), "x")
    assert (docs / "a.txt").read_text() == "x"


def test_write_outside_declared_write_dirs(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1", {"write_dirs": [str(docs)]})
    with pytest.raises(FilePermissionError):
        fs.write_text(str(uploads / "a.txt"), "x")


# ---------------- delete 操作（§4.2 allow_delete） ----------------
def test_delete_disallowed_without_allow_delete(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1", {"write_dirs": [str(docs)], "allow_delete": False})
    (docs / "a.txt").write_text("x")
    with pytest.raises(FilePermissionError):
        fs.delete(str(docs / "a.txt"))


def test_delete_allowed_with_allow_delete(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1", {"write_dirs": [str(docs)], "allow_delete": True})
    (docs / "a.txt").write_text("x")
    fs.delete(str(docs / "a.txt"))
    assert not (docs / "a.txt").exists()


def test_delete_requires_write_dirs(monkeypatch, tmp_path):
    uploads, docs = _setup_whitelist(monkeypatch, tmp_path)
    fs = FileAccessorImpl("p1", {"write_dirs": [str(docs)], "allow_delete": True})
    (uploads / "a.txt").write_text("x")
    with pytest.raises(FilePermissionError):
        fs.delete(str(uploads / "a.txt"))  # uploads 不在 write_dirs


# ---------------- 目录子集校验（§4.3 第1条） ----------------
def test_file_permissions_subset_valid():
    from nvwa_agent.core.plugin_runtime.scanner import _validate_file_permissions

    assert _validate_file_permissions(
        {"file_permissions": {"read_dirs": ["./data/uploads"]}},
        ["./data/uploads", "./data/generated_docs"],
    ) == []


def test_file_permissions_subset_outside():
    from nvwa_agent.core.plugin_runtime.scanner import _validate_file_permissions

    errors = _validate_file_permissions(
        {"file_permissions": {"read_dirs": ["./data/secret"]}},
        ["./data/uploads"],
    )
    assert any("read_dirs" in e for e in errors)


def test_file_permissions_no_declaration_no_error():
    from nvwa_agent.core.plugin_runtime.scanner import _validate_file_permissions

    assert _validate_file_permissions({}, ["./data/uploads"]) == []
