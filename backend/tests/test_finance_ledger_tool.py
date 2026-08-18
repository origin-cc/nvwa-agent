"""finance-ledger-tool 单元测试：stub ctx + 内存 fs。

覆盖：add→stats 闭环（含支出分类排行）、负数金额/非法 action 拒绝且账本不变、
空账本 query/stats 提示、query 按 category/month 过滤、跨月记录不计入 stats。
插件代码经 importlib 从 plugins/finance-ledger-tool/main.py 加载。
"""
import importlib.util
import json
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "finance-ledger-tool"
LEDGER_PATH = "data/generated_docs/finance_ledger.json"


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "finance_ledger_tool_main", PLUGIN_DIR / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_plugin()


class _MemFs:
    """内存文件系统：dict 存储；read_text 不存在抛 FileNotFoundError。"""

    def __init__(self):
        self.files = {}

    def read_text(self, path, encoding="utf-8"):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_text(self, path, content, encoding="utf-8"):
        self.files[path] = content
        return path

    def list_dir(self, path):
        return []


class _CtxStub:
    def __init__(self, fs):
        self.plugin_id = "finance-ledger-tool"
        self.config = {}
        self.fs = fs


def _setup():
    fs = _MemFs()
    ctx = _CtxStub(fs)
    tool = mod.on_load(ctx)
    return tool, ctx, fs


def _add(tool, ctx, **kwargs):
    return tool.execute(ctx, {"action": "add", **kwargs})


# ---------------- add → stats 闭环（含支出分类排行） ----------------
def test_add_then_stats_closed_loop():
    tool, ctx, fs = _setup()
    r1 = _add(tool, ctx, amount=25.5, type="expense", category="餐饮", date="2026-07-01")
    assert r1.ok and "已记账" in r1.data and "25.50" in r1.data
    assert _add(tool, ctx, amount=12.5, type="expense", category="餐饮",
                date="2026-07-02").ok
    assert _add(tool, ctx, amount=8, type="expense", category="交通",
                date="2026-07-03").ok
    assert _add(tool, ctx, amount=10000, type="income", category="工资",
                date="2026-07-05", note="7月工资").ok

    result = tool.execute(ctx, {"action": "stats", "month": "2026-07"})
    assert result.ok
    text = result.data
    assert "总收入：10000.00 元" in text
    assert "总支出：46.00 元" in text
    assert "净结余：9954.00 元" in text
    # 支出分类排行：餐饮 38.00 居首，交通 8.00 次之
    assert "餐饮: 38.00" in text
    assert "交通: 8.00" in text
    assert text.index("餐饮: 38.00") < text.index("交通: 8.00")

    # 账本已持久化，记录字段完整
    ledger = json.loads(fs.files[LEDGER_PATH])
    assert len(ledger["records"]) == 4
    assert ledger["records"][0] == {
        "date": "2026-07-01", "type": "expense",
        "amount": 25.5, "category": "餐饮", "note": "",
    }


# ---------------- 缺省 date/month：落今天/当月 ----------------
def test_add_and_stats_default_to_today():
    tool, ctx, _ = _setup()
    assert _add(tool, ctx, amount=9.9, type="expense", category="零食").ok
    result = tool.execute(ctx, {"action": "stats"})  # 缺省当月
    assert result.ok
    assert "9.90" in result.data


# ---------------- 负数金额 / 非法 action 拒绝且账本不变 ----------------
def test_reject_negative_amount_and_invalid_action():
    tool, ctx, fs = _setup()
    assert _add(tool, ctx, amount=10, type="expense", category="餐饮",
                date="2026-07-01").ok
    snapshot = dict(fs.files)

    bad_amount = _add(tool, ctx, amount=-5, type="expense", category="餐饮")
    assert not bad_amount.ok and bad_amount.error_code == "TOOL_EXEC_ERROR"

    zero_amount = _add(tool, ctx, amount=0, type="expense", category="餐饮")
    assert not zero_amount.ok and zero_amount.error_code == "TOOL_EXEC_ERROR"

    bad_action = tool.execute(ctx, {
        "action": "delete", "amount": 5, "type": "expense", "category": "餐饮",
    })
    assert not bad_action.ok and bad_action.error_code == "TOOL_EXEC_ERROR"

    assert fs.files == snapshot  # 账本保持不变


# ---------------- add 参数校验 ----------------
def test_add_param_validation():
    tool, ctx, fs = _setup()
    bad_type = _add(tool, ctx, amount=10, type="cost", category="餐饮")
    assert not bad_type.ok and bad_type.error_code == "TOOL_EXEC_ERROR"

    missing_category = _add(tool, ctx, amount=10, type="expense")
    assert not missing_category.ok and missing_category.error_code == "TOOL_EXEC_ERROR"

    bad_date = _add(tool, ctx, amount=10, type="expense", category="餐饮",
                    date="2026/07/01")
    assert not bad_date.ok and bad_date.error_code == "TOOL_EXEC_ERROR"

    bad_month = tool.execute(ctx, {"action": "query", "month": "2026-7"})
    assert not bad_month.ok and bad_month.error_code == "TOOL_EXEC_ERROR"

    assert fs.files == {}  # 全部被拒，账本未落盘


# ---------------- 空账本 query / stats ----------------
def test_empty_ledger_query_and_stats():
    tool, ctx, _ = _setup()  # 无账本文件
    q = tool.execute(ctx, {"action": "query", "month": "2026-01"})
    assert q.ok and q.data == "该条件下暂无账目记录"

    q_default = tool.execute(ctx, {"action": "query"})  # 缺省当月
    assert q_default.ok and q_default.data == "该条件下暂无账目记录"

    s = tool.execute(ctx, {"action": "stats", "month": "2026-01"})
    assert s.ok and s.data == "该月暂无账目，无法统计"


# ---------------- query 按 month / category 过滤 ----------------
def test_query_filter_by_month_and_category():
    tool, ctx, _ = _setup()
    for kwargs in [
        {"amount": 30, "type": "expense", "category": "餐饮", "date": "2026-07-01"},
        {"amount": 20, "type": "expense", "category": "交通", "date": "2026-07-02"},
        {"amount": 40, "type": "expense", "category": "餐饮", "date": "2026-08-03"},
    ]:
        assert _add(tool, ctx, **kwargs).ok

    # 仅按 month 过滤：7 月两条，不含 8 月的 40
    july = tool.execute(ctx, {"action": "query", "month": "2026-07"})
    assert july.ok
    assert "30.00" in july.data and "20.00" in july.data
    assert "40.00" not in july.data
    assert "共 2 条" in july.data

    # month + category 联合过滤：只剩 7 月餐饮 30
    cat = tool.execute(ctx, {"action": "query", "month": "2026-07", "category": "餐饮"})
    assert cat.ok
    assert "30.00" in cat.data
    assert "交通" not in cat.data
    assert "共 1 条" in cat.data


# ---------------- 跨月记录不计入 stats ----------------
def test_stats_excludes_other_months():
    tool, ctx, _ = _setup()
    assert _add(tool, ctx, amount=100, type="expense", category="餐饮",
                date="2026-07-10").ok
    assert _add(tool, ctx, amount=250.5, type="expense", category="购物",
                date="2026-08-11").ok

    july = tool.execute(ctx, {"action": "stats", "month": "2026-07"})
    assert july.ok
    assert "总支出：100.00 元" in july.data
    assert "250.50" not in july.data  # 8 月记录不计入
    assert "购物" not in july.data

    august = tool.execute(ctx, {"action": "stats", "month": "2026-08"})
    assert august.ok
    assert "总支出：250.50 元" in august.data
    assert "餐饮" not in august.data
