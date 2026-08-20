"""会话上下文管理：从 task_record 重建对话历史，超窗口旧轮次折叠为滚动摘要。

- 单一事实源：同会话已完成的 task_record（input_prompt -> result），不单独存消息；
- 窗口策略（对齐 DeepSeek Harness 的阈值+保留比例语义）：历史（摘要 + 未折叠原文）
  字符数达到窗口阈值（thresholdRatio=1.0）才压缩；压缩时保留最近 retain_ratio×窗口
  字符的原文，其余整体「替换」为一条滚动摘要；
- 摘要失败降级：待折叠轮次与保留轮次一并原文注入，不阻断任务。
"""
from dataclasses import dataclass

from nvwa_agent.core.llm import get_llm_client
from nvwa_agent.core.log import get_core_logger
from nvwa_agent.database import session_scope
from nvwa_agent.models.task import ConversationSummary, TaskRecord

_log = get_core_logger()


@dataclass
class Turn:
    """一轮对话：task_id 用于增量摘要覆盖判定。"""

    task_id: str
    user: str
    assistant: str


def load_finished_turns(conversation_id: str, exclude_task_id: str) -> list[Turn]:
    """按对话时间序返回同会话已完成轮次（排除当前任务）。"""
    with session_scope() as db:
        rows = (
            db.query(TaskRecord)
            .filter(
                TaskRecord.conversation_id == conversation_id,
                TaskRecord.status == "finish",
                TaskRecord.result.isnot(None),
                TaskRecord.result != "",
                TaskRecord.task_id != exclude_task_id,
            )
            .order_by(TaskRecord.created_at.asc(), TaskRecord.task_id.asc())
            .all()
        )
        return [
            Turn(task_id=r.task_id, user=r.input_prompt or "", assistant=r.result or "")
            for r in rows
        ]


def expand_turns(turns: list[Turn]) -> list[dict]:
    """把轮次展开为 OpenAI 风格 user/assistant 消息列表。"""
    messages: list[dict] = []
    for turn in turns:
        messages.append({"role": "user", "content": turn.user})
        messages.append({"role": "assistant", "content": turn.assistant})
    return messages


def _turn_chars(turn: Turn) -> int:
    """单轮字符数（user + assistant）。"""
    return len(turn.user) + len(turn.assistant)


def _turns_chars(turns: list[Turn]) -> int:
    """轮次总字符数（用字符数近似 token，中文约 2 字符 ≈ 1 token）。"""
    return sum(_turn_chars(t) for t in turns)


def _split_recent(turns: list[Turn], budget: int) -> tuple[list[Turn], list[Turn]]:
    """从最新往回保留不超过 budget 字符的原文（至少保留最新 1 轮）。

    返回 (to_fold, keep)：to_fold 为最旧、应折叠的轮次；keep 为最新、保留原文的轮次。
    """
    keep: list[Turn] = []
    acc = 0
    for t in reversed(turns):
        t_chars = _turn_chars(t)
        if keep and acc + t_chars > budget:
            break
        keep.append(t)
        acc += t_chars
    keep.reverse()
    return turns[:-len(keep)], keep


def build_conversation_context(conversation_id: str, exclude_task_id: str,
                               window_chars: int, retain_ratio: float) -> list[dict]:
    """构建注入模型的上下文消息。

    语义（对齐 DeepSeek Harness 阈值 + 保留比例）：
    - 历史可见字符 = 已有摘要 + 未折叠原文；
    - 未超窗口（≤ window_chars）：全部原文注入，不压缩（内容少不压缩）；
    - 超窗口：保留最近 retain_ratio×window 字符的原文，其余整体替换为一条滚动摘要。
    注入结构 = [摘要] + expand(待折叠轮次, 仅摘要失败时) + expand(保留轮次)。
    """
    turns = load_finished_turns(conversation_id, exclude_task_id)
    if not turns:
        return []

    previous, covered = _load_summary(conversation_id)
    uncompacted = turns[covered:]  # 尚未折叠进摘要的轮次
    visible_chars = len(previous) + _turns_chars(uncompacted)

    if visible_chars <= window_chars:
        messages: list[dict] = []
        if previous:
            messages.append({"role": "user", "content": "【对话历史摘要】\n" + previous})
        messages.extend(expand_turns(uncompacted))
        return messages

    retain_budget = max(1, int(window_chars * retain_ratio))
    to_fold, keep = _split_recent(uncompacted, retain_budget)

    summary = previous
    if to_fold:
        merged = _summarize(previous, to_fold)
        if merged is not None:
            summary = merged
            _save_summary(conversation_id, summary, covered + len(to_fold))
            to_fold = []  # 已替换进摘要，不再以原文注入

    messages = []
    if summary:
        messages.append({"role": "user", "content": "【对话历史摘要】\n" + summary})
    messages.extend(expand_turns(to_fold))  # 摘要失败时原文注入（零丢失）
    messages.extend(expand_turns(keep))
    return messages


def _load_summary(conversation_id: str) -> tuple[str, int]:
    """返回 (摘要文本, 已折叠轮数)，无记录时为 ("", 0)。"""
    with session_scope() as db:
        row = db.get(ConversationSummary, conversation_id)
        if row is None:
            return "", 0
        return row.summary or "", row.covered_turns or 0


def _save_summary(conversation_id: str, summary: str, covered_turns: int) -> None:
    """持久化滚动摘要（覆盖语义）。"""
    with session_scope() as db:
        row = db.get(ConversationSummary, conversation_id)
        if row is None:
            db.add(ConversationSummary(
                conversation_id=conversation_id,
                summary=summary,
                covered_turns=covered_turns,
            ))
        else:
            row.summary = summary
            row.covered_turns = covered_turns


def _summarize(previous: str, new_turns: list[Turn]) -> str | None:
    """用 LLM 把旧摘要与新落入窗口外的轮次合并为一条滚动摘要。"""
    transcript = "\n".join(
        f"用户：{t.user}\n助手：{t.assistant}" for t in new_turns
    )
    system = (
        "你是会话上下文压缩引擎。请把已有的历史摘要与新增对话合并成一条简洁的滚动摘要，"
        "保留关键事实（金额、分类、日期、决策、未完成事项、用户偏好等），"
        "用中文输出纯文本，不要输出 JSON 或其他格式。"
    )
    user = f"【已有摘要】\n{previous or '（无）'}\n\n【新增对话】\n{transcript}"
    try:
        raw = get_llm_client().chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            stream=False,
        )
        text = str(raw).strip()
        return text or None
    except Exception as exc:  # LLM 不可用/网络异常等：降级不阻断任务
        _log.warning("会话滚动摘要生成失败：%s", exc)
        return None
