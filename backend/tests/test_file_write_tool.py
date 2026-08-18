"""file-write-tool 单元测试：stub ctx/fs，覆盖成功写入、路径越权、缺参数。

插件代码经 importlib 从 plugins/file-write-tool/main.py 加载；
nvwa_agent.sdk 由 backend 目录（pytest 运行根）提供，无需 stub。
"""
import importlib.util
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "file-write-tool"


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "file_write_tool_main", PLUGIN_DIR / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_plugin()


class _FsStub:
    """fs stub：记录 write_text 调用；可注入抛 PermissionError 模拟路径越权。"""

    def __init__(self, permission_denied: bool = False):
        self.writes = []  # [(path, content)]
        self.permission_denied = permission_denied

    def write_text(self, path, content, encoding="utf-8"):
        if self.permission_denied:
            raise PermissionError(f"路径超出白名单目录: {path}")
        self.writes.append((path, content))
        return path

    def read_text(self, path, encoding="utf-8"):
        raise FileNotFoundError(path)

    def list_dir(self, path):
        return []


class _CtxStub:
    def __init__(self, fs):
        self.plugin_id = "file-write-tool"
        self.config = {}
        self.fs = fs


def _setup(permission_denied: bool = False):
    fs = _FsStub(permission_denied=permission_denied)
    ctx = _CtxStub(fs)
    tool = mod.on_load(ctx)
    return tool, ctx, fs


# ---------------- on_load 生命周期契约 ----------------
def test_on_load_returns_instance():
    tool, _, _ = _setup()
    assert isinstance(tool, mod.FileWriteTool)
    assert tool.tool_name == "file-write-tool:write_text"


# ---------------- 成功写入 ----------------
def test_write_success_returns_path():
    tool, ctx, fs = _setup()
    result = tool.execute(ctx, {
        "path": "generated_docs/note.md",
        "content": "# 标题\n正文内容",
    })
    assert result.ok
    assert result.data == "已写入: generated_docs/note.md"
    assert fs.writes == [("generated_docs/note.md", "# 标题\n正文内容")]


# ---------------- 路径越权 → FILE_PERMISSION_DENIED ----------------
def test_write_permission_denied():
    tool, ctx, fs = _setup(permission_denied=True)
    result = tool.execute(ctx, {"path": "uploads/../../etc/passwd", "content": "x"})
    assert not result.ok
    assert result.error_code == "FILE_PERMISSION_DENIED"
    assert result.error_msg
    assert fs.writes == []


# ---------------- 缺参数 → TOOL_EXEC_ERROR ----------------
def test_missing_path_rejected():
    tool, ctx, fs = _setup()
    result = tool.execute(ctx, {"content": "x"})
    assert not result.ok
    assert result.error_code == "TOOL_EXEC_ERROR"
    assert fs.writes == []


def test_missing_content_rejected():
    tool, ctx, fs = _setup()
    result = tool.execute(ctx, {"path": "data/generated_docs/a.md"})
    assert not result.ok
    assert result.error_code == "TOOL_EXEC_ERROR"
    assert fs.writes == []
    # content 显式传 None 同样视为缺失
    result = tool.execute(ctx, {"path": "data/generated_docs/a.md", "content": None})
    assert not result.ok
    assert result.error_code == "TOOL_EXEC_ERROR"
