"""个人记账理财账本工具插件：记账(add) / 查账(query) / 消费统计(stats)。

账本持久化于白名单目录 data/generated_docs/finance_ledger.json，
文件访问一律经 ctx.fs（越权抛 PermissionError → FILE_PERMISSION_DENIED）。
"""
import json
import re
from datetime import date, datetime

from nvwa_agent.sdk import BaseToolPlugin, PluginContext, ToolResult

LEDGER_PATH = "data/generated_docs/finance_ledger.json"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def on_load(ctx: PluginContext) -> "FinanceLedgerTool":
    return FinanceLedgerTool()


def _valid_date(value) -> bool:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _valid_month(value) -> bool:
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError:
        return False
    return True


class FinanceLedgerTool(BaseToolPlugin):
    tool_name = "finance-ledger-tool:ledger"
    description = (
        "个人记账理财账本：action=add 记一笔账（收入/支出）、action=query 查询账目、"
        "action=stats 汇总统计收支与分类排行。记账、查账、消费分析必须调用本工具，"
        "禁止凭记忆编造账目"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "query", "stats"],
                "description": "操作：add 记账 / query 查账 / stats 统计",
            },
            "amount": {"type": "number", "description": "金额（正数，add 必填）"},
            "type": {
                "type": "string",
                "enum": ["income", "expense"],
                "description": "收支类型（add 必填）",
            },
            "category": {
                "type": "string",
                "description": "分类（add 必填，如 餐饮/交通/购物/工资；query 可选过滤）",
            },
            "note": {"type": "string", "description": "备注（可选）"},
            "date": {"type": "string", "description": "记账日期 YYYY-MM-DD（缺省今天）"},
            "month": {"type": "string", "description": "查询/统计月份 YYYY-MM（缺省当月）"},
        },
        "required": ["action"],
    }

    # ---------------- 账本读写（ctx.fs 白名单目录） ----------------
    def _load(self, ctx: PluginContext) -> dict:
        if getattr(ctx, "fs", None) is None:
            return {"records": []}
        try:
            raw = ctx.fs.read_text(LEDGER_PATH)
        except FileNotFoundError:
            return {"records": []}
        try:
            data = json.loads(raw)
        except ValueError:  # JSON 解析失败 → 视为空账本
            return {"records": []}
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            return {"records": []}
        return data

    def _save(self, ctx: PluginContext, ledger: dict) -> None:
        if getattr(ctx, "fs", None) is None:
            raise RuntimeError("文件系统不可用（ctx.fs 未注入），无法保存账本")
        ctx.fs.write_text(LEDGER_PATH, json.dumps(ledger, ensure_ascii=False))

    # ---------------- execute 分发 ----------------
    def execute(self, ctx: PluginContext, args: dict) -> ToolResult:
        action = args.get("action")
        if action not in ("add", "query", "stats"):
            return ToolResult.failure("TOOL_EXEC_ERROR", f"非法 action: {action}")
        try:
            if action == "add":
                return self._add(ctx, args)
            if action == "query":
                return self._query(ctx, args)
            return self._stats(ctx, args)
        except PermissionError as exc:
            return ToolResult.failure("FILE_PERMISSION_DENIED", f"文件访问越权: {exc}")
        except Exception as exc:
            return ToolResult.failure("TOOL_EXEC_ERROR", f"账本操作失败: {exc}")

    # ---------------- action=add：记一笔账 ----------------
    def _add(self, ctx: PluginContext, args: dict) -> ToolResult:
        if args.get("amount") is None:
            return ToolResult.failure("TOOL_EXEC_ERROR", "add 缺少参数 amount")
        try:
            amount = float(args["amount"])
        except (TypeError, ValueError):
            return ToolResult.failure("TOOL_EXEC_ERROR", f"amount 必须为数字: {args['amount']}")
        if amount <= 0:
            return ToolResult.failure("TOOL_EXEC_ERROR", f"amount 必须为正数: {args['amount']}")
        rtype = args.get("type")
        if rtype not in ("income", "expense"):
            return ToolResult.failure("TOOL_EXEC_ERROR", "type 必须为 income 或 expense")
        category = str(args.get("category") or "").strip()
        if not category:
            return ToolResult.failure("TOOL_EXEC_ERROR", "add 缺少参数 category")
        day = args.get("date") or date.today().isoformat()
        if not _valid_date(day):
            return ToolResult.failure(
                "TOOL_EXEC_ERROR", f"date 格式错误（应为 YYYY-MM-DD）: {args.get('date')}"
            )
        note = str(args.get("note") or "").strip()

        ledger = self._load(ctx)
        ledger.setdefault("records", []).append(
            {"date": day, "type": rtype, "amount": amount, "category": category, "note": note}
        )
        self._save(ctx, ledger)

        type_cn = "收入" if rtype == "income" else "支出"
        summary = f"已记账：{day} {type_cn} {category} {amount:.2f} 元"
        if note:
            summary += f"（备注：{note}）"
        return ToolResult.success(summary)

    # ---------------- action=query：查询账目 ----------------
    def _query(self, ctx: PluginContext, args: dict) -> ToolResult:
        month = args.get("month") or date.today().strftime("%Y-%m")
        if not _valid_month(month):
            return ToolResult.failure(
                "TOOL_EXEC_ERROR", f"month 格式错误（应为 YYYY-MM）: {args.get('month')}"
            )
        category = str(args.get("category") or "").strip()
        records = [
            r for r in self._load(ctx)["records"]
            if str(r.get("date", "")).startswith(month)
            and (not category or r.get("category") == category)
        ]
        if not records:
            return ToolResult.success("该条件下暂无账目记录")

        lines = []
        income_total = expense_total = 0.0
        for r in records:
            amount = float(r.get("amount") or 0)
            if r.get("type") == "income":
                income_total += amount
            else:
                expense_total += amount
            type_cn = "收入" if r.get("type") == "income" else "支出"
            note = f"（{r.get('note')}）" if r.get("note") else ""
            lines.append(
                f"{r.get('date')} {type_cn} {r.get('category')} {amount:.2f} 元{note}"
            )
        lines.append(
            f"共 {len(records)} 条，小计：收入 {income_total:.2f} 元、支出 {expense_total:.2f} 元"
        )
        return ToolResult.success("\n".join(lines))

    # ---------------- action=stats：汇总统计 ----------------
    def _stats(self, ctx: PluginContext, args: dict) -> ToolResult:
        month = args.get("month") or date.today().strftime("%Y-%m")
        if not _valid_month(month):
            return ToolResult.failure(
                "TOOL_EXEC_ERROR", f"month 格式错误（应为 YYYY-MM）: {args.get('month')}"
            )
        records = [
            r for r in self._load(ctx)["records"]
            if str(r.get("date", "")).startswith(month)
        ]
        if not records:
            return ToolResult.success("该月暂无账目，无法统计")

        total_income = total_expense = 0.0
        expense_by_category: dict[str, float] = {}
        for r in records:
            amount = float(r.get("amount") or 0)
            if r.get("type") == "income":
                total_income += amount
            else:
                total_expense += amount
                cat = str(r.get("category") or "未分类")
                expense_by_category[cat] = expense_by_category.get(cat, 0.0) + amount

        lines = [
            f"{month} 收支统计：",
            f"总收入：{total_income:.2f} 元",
            f"总支出：{total_expense:.2f} 元",
            f"净结余：{total_income - total_expense:.2f} 元",
            "支出分类排行：",
        ]
        for i, (cat, amt) in enumerate(
            sorted(expense_by_category.items(), key=lambda kv: kv[1], reverse=True), 1
        ):
            lines.append(f"{i}. {cat}: {amt:.2f} 元")
        return ToolResult.success("\n".join(lines))
