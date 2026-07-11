import threading
from dataclasses import dataclass, field
from datetime import datetime

PENDING_TERMINAL_CONTEXT_TTL_SECONDS = 15 * 60
MAX_STORED_COMMAND_LENGTH = 500
MAX_STORED_TERMINAL_FEEDBACK_LENGTH = 1600

_CONTINUATION_MARKERS = (
    "开了",
    "打开",
    "启动",
    "连上",
    "连接",
    "好了",
    "可以了",
    "继续",
    "重试",
    "再试",
    "试试",
    "刚才",
    "上面",
    "那个",
    "终端",
    "terminal",
    "命令",
    "没开",
    "未连接",
    "没发",
    "没执行",
    "为什么",
    "怎么回事",
)


@dataclass(frozen=True)
class PendingTerminalContinuation:
    item_id: str
    command: str
    reason: str
    message: str
    tool_name: str
    created_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        age = (datetime.now() - self.created_at).total_seconds()
        return age > PENDING_TERMINAL_CONTEXT_TTL_SECONDS

    def elapsed_seconds(self) -> int:
        return max(0, int((datetime.now() - self.created_at).total_seconds()))


_pending_terminal_contexts: dict[str, PendingTerminalContinuation] = {}
_pending_terminal_lock = threading.RLock()


def _normalize_command(command: str) -> str:
    return " ".join(str(command or "").strip().split())


def _short_command(command: str) -> str:
    normalized = _normalize_command(command)
    if len(normalized) <= MAX_STORED_COMMAND_LENGTH:
        return normalized
    return normalized[: MAX_STORED_COMMAND_LENGTH - 3] + "..."


def _short_terminal_feedback(feedback: str) -> str:
    normalized = str(feedback or "").strip()
    if len(normalized) <= MAX_STORED_TERMINAL_FEEDBACK_LENGTH:
        return normalized
    head_length = MAX_STORED_TERMINAL_FEEDBACK_LENGTH // 2
    tail_length = MAX_STORED_TERMINAL_FEEDBACK_LENGTH - head_length - 30
    return f"{normalized[:head_length]}\n...<truncated>...\n{normalized[-tail_length:]}"


def record_pending_terminal_continuation(
    *,
    item_id: str,
    command: str,
    reason: str,
    message: str,
    tool_name: str,
) -> None:
    item_key = str(item_id or "").strip()
    command_text = _short_command(command)
    if not item_key or not command_text:
        return

    with _pending_terminal_lock:
        _pending_terminal_contexts[item_key] = PendingTerminalContinuation(
            item_id=item_key,
            command=command_text,
            reason=str(reason or "").strip(),
            message=str(message or "").strip(),
            tool_name=str(tool_name or "").strip(),
        )


def get_pending_terminal_continuation(
    item_id: str,
) -> PendingTerminalContinuation | None:
    item_key = str(item_id or "").strip()
    if not item_key:
        return None

    with _pending_terminal_lock:
        pending = _pending_terminal_contexts.get(item_key)
        if pending and pending.is_expired():
            _pending_terminal_contexts.pop(item_key, None)
            return None
        return pending


def clear_pending_terminal_continuation(
    item_id: str,
    *,
    command: str | None = None,
) -> None:
    item_key = str(item_id or "").strip()
    if not item_key:
        return

    with _pending_terminal_lock:
        pending = _pending_terminal_contexts.get(item_key)
        if not pending:
            return
        if command is not None and _normalize_command(command) != _normalize_command(
            pending.command
        ):
            return
        _pending_terminal_contexts.pop(item_key, None)


def attach_terminal_feedback_to_pending_continuation(
    item_id: str,
    feedback: str,
) -> None:
    item_key = str(item_id or "").strip()
    feedback_text = _short_terminal_feedback(feedback)
    if not item_key or not feedback_text:
        return

    with _pending_terminal_lock:
        pending = _pending_terminal_contexts.get(item_key)
        if not pending:
            return
        if pending.is_expired():
            _pending_terminal_contexts.pop(item_key, None)
            return
        _pending_terminal_contexts[item_key] = PendingTerminalContinuation(
            item_id=pending.item_id,
            command=pending.command,
            reason="terminal_feedback_after_reconnect",
            message=(
                "上一条命令起初没有发进终端；后来终端出现了这段反馈：\n"
                f"{feedback_text}"
            ),
            tool_name=pending.tool_name,
            created_at=pending.created_at,
        )


def _message_matches_pending_terminal_continuation(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return False
    if any(marker in normalized for marker in _CONTINUATION_MARKERS):
        return True
    return len(normalized) <= 12 and normalized in {"q", "ok", "好", "嗯", "行"}


def build_pending_terminal_continuation_prompt(item_id: str, message: str) -> str:
    pending = get_pending_terminal_continuation(item_id)
    if not pending:
        return ""
    if not _message_matches_pending_terminal_continuation(message):
        return ""

    result_text = pending.message or pending.reason or "上一条终端命令没有进入终端"
    return (
        "当前有一个未解决的短期终端上下文。这不是长期记忆，只用于理解本轮对话：\n"
        f"- 上一条终端命令：`{pending.command}`\n"
        f"- 当时结果：{result_text}\n"
        f"- 距今约 {pending.elapsed_seconds()} 秒\n"
        "如果用户当前消息是在说终端已经打开/连接、继续、重试、刚才那条命令，"
        "或询问为什么没执行，请把它理解为接着处理上一条命令。"
        "优先调用 `mcp_local_execute_command` 重试/验证上一条命令；"
        "如果用户只是询问原因，就解释上一条命令当时没发进终端。"
        "不要把这条短期上下文写入长期记忆。"
    )


def clear_all_pending_terminal_continuations() -> None:
    with _pending_terminal_lock:
        _pending_terminal_contexts.clear()
