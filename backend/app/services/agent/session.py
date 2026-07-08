import asyncio
import hashlib
import json
import logging
import queue
import re
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from litellm import completion

from app.services.agent.agent import Agent, agent_manager
from app.services.agent.history.chat import append_chat_message
from app.services.agent.integrations import (
    clear_terminal_alert_integration_tools,
    ensure_terminal_alert_integration_tools,
    extract_integration_context_targets,
    should_enable_terminal_alert_integrations,
)
from app.services.agent.prompts.builder import (
    build_chat_turn_messages,
    build_terminal_turn_messages,
    is_critical_terminal_event,
)
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.tool_grounding import guard_ungrounded_tool_claim
from app.services.agent.tool_arguments import (
    ToolArgumentParseError,
    parse_tool_arguments,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 120
MAX_ITERATIONS = 6
LOOP_DETECTION_WINDOW = 6
LOOP_THRESHOLD = 3
MAX_QUEUE_SIZE = 100
MAX_TOOL_CALLS = 8
MAX_REPEATED_LOG_READS = 2
MAX_NO_PROGRESS_STEPS = 3
MAX_TURN_DURATION_SECONDS = 45
PENDING_COMMAND_TIMEOUT_SECONDS = 20
PENDING_COMMAND_RECHECK_SECONDS = 0.25
PENDING_COMMAND_STALLED_CONFIRM_SECONDS = 2.0
READ_LOG_TOOL_NAME = "mcp_local_read_terminal_log"
COMMAND_TOOL_NAMES = {
    "mcp_local_execute_command",
    "mcp_local_interrupt_command",
}
COMMAND_DISPATCH_FAILURE_MESSAGE = "终端未连接或未打开，命令没有发送。请先启动或连接终端后再试。"
COMMAND_DISPATCH_FAILURE_MARKERS = (
    "命令发送失败",
    "终端未连接",
    "终端未打开",
    "终端未收到命令",
)
EXECUTE_COMMAND_TOOL_NAME = "mcp_local_execute_command"
TERMINAL_INPUT_MODE_BUSY = "busy"
TERMINAL_INPUT_MODE_CONSOLE = "console"
TERMINAL_INPUT_CONTEXT_TTL_SECONDS = 6 * 60 * 60
TERMINAL_BUSY_COMMAND_PATTERNS = (
    r"^(?:sudo\s+)?(?:apt|apt-get|aptitude)\s+(?:update|upgrade|full-upgrade|dist-upgrade|install|remove|autoremove)\b",
    r"^(?:sudo\s+)?(?:dnf|yum)\s+(?:install|update|upgrade|remove|groupinstall)\b",
    r"^(?:sudo\s+)?apk\s+(?:add|update|upgrade|del)\b",
    r"^(?:sudo\s+)?pacman\s+-S(?:yu?)?\b",
    r"^(?:sudo\s+)?zypper\s+(?:install|update|refresh|remove)\b",
    r"^(?:python\d*(?:\.\d+)?\s+-m\s+pip|pip\d*|uv\s+pip)\s+install\b",
    r"^uv\s+sync\b",
    r"^(?:npm|pnpm|yarn|bun)\s+(?:install|ci|add|update|upgrade)\b",
    r"^docker\s+(?:build|compose\s+build|compose\s+up)\b",
    r"^(?:curl|wget)\b.*(?:https?://|ftp://)",
    r"^git\s+(?:clone|pull|fetch|submodule\s+update)\b",
    r"^(?:make|cmake\s+--build|cargo\s+(?:build|install)|go\s+(?:build|install)|mvn|gradle|\./gradlew)\b",
)
TERMINAL_CONSOLE_COMMAND_PATTERNS = (
    r"\bjava\s+.*(?:-jar\s+\S*(?:server|paper|spigot|forge|fabric|bukkit|mohist|arclight|minecraft)\S*|nogui)\b",
    r"\bbedrock_server\b",
)
MINECRAFT_CONSOLE_COMMANDS = frozenset(
    {
        "advancement",
        "ban",
        "ban-ip",
        "banlist",
        "clear",
        "deop",
        "difficulty",
        "effect",
        "enchant",
        "execute",
        "experience",
        "fill",
        "forceload",
        "function",
        "gamemode",
        "gamerule",
        "give",
        "help",
        "kick",
        "kill",
        "list",
        "locate",
        "me",
        "msg",
        "op",
        "pardon",
        "pardon-ip",
        "particle",
        "playsound",
        "reload",
        "save-all",
        "save-off",
        "save-on",
        "say",
        "schedule",
        "scoreboard",
        "seed",
        "setblock",
        "setidletimeout",
        "setworldspawn",
        "spawnpoint",
        "spectate",
        "spreadplayers",
        "stop",
        "summon",
        "tag",
        "team",
        "teleport",
        "tell",
        "tellraw",
        "time",
        "title",
        "tp",
        "weather",
        "whitelist",
        "worldborder",
        "xp",
    }
)
SILENT_TOOL_NAMES = {READ_LOG_TOOL_NAME, "mcp_robot_send_message", "mcp_robot_sleep_conversation", "mcp_robot_save_memory"}
TERMINAL_SOURCE_FILTERED = "filtered_output"
TERMINAL_SOURCE_RAW_FEEDBACK = "raw_feedback"


def is_command_dispatch_failure_result(tool_name: str, result_text: str) -> bool:
    if tool_name not in COMMAND_TOOL_NAMES:
        return False
    return any(marker in (result_text or "") for marker in COMMAND_DISPATCH_FAILURE_MARKERS)


def _normalize_command_for_routing(command: str) -> str:
    return " ".join((command or "").strip().split()).lower()


def classify_terminal_input_mode(command: str) -> str | None:
    normalized = _normalize_command_for_routing(command)
    if not normalized:
        return None
    if any(re.search(pattern, normalized) for pattern in TERMINAL_CONSOLE_COMMAND_PATTERNS):
        return TERMINAL_INPUT_MODE_CONSOLE
    if any(re.search(pattern, normalized) for pattern in TERMINAL_BUSY_COMMAND_PATTERNS):
        return TERMINAL_INPUT_MODE_BUSY
    return None


def _first_command_token(command: str) -> str:
    normalized = _normalize_command_for_routing(command)
    if not normalized:
        return ""
    if normalized.startswith("/"):
        normalized = normalized[1:].strip()
    return normalized.split(maxsplit=1)[0]


def is_terminal_console_command(command: str) -> bool:
    stripped = (command or "").strip()
    if not stripped or "\n" in stripped or "\r" in stripped:
        return False
    if re.search(r"[;&|`$<>]", stripped):
        return False
    return _first_command_token(stripped) in MINECRAFT_CONSOLE_COMMANDS


class SessionState(Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    COOLDOWN = "cooldown"


class InputType(Enum):
    TERMINAL = "terminal"
    CHAT = "chat"


@dataclass
class InputMessage:
    input_type: InputType
    content: str
    raw_content: str = ""
    query: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    callback: Callable | None = None


@dataclass
class TurnGuard:
    turn_id: str = field(default_factory=lambda: uuid4().hex[:8])
    started_at: datetime = field(default_factory=datetime.now)
    tool_call_count: int = 0
    waiting_for_terminal_feedback: bool = False
    no_progress_steps: int = 0
    last_progress_token: str | None = None
    last_log_fingerprint: str | None = None
    repeated_log_reads: int = 0
    recent_steps: deque[str] = field(
        default_factory=lambda: deque(maxlen=LOOP_DETECTION_WINDOW)
    )

    def check_timeout(self) -> tuple[bool, str]:
        elapsed = (datetime.now() - self.started_at).total_seconds()
        if elapsed > MAX_TURN_DURATION_SECONDS:
            return True, f"当前轮处理超时 ({MAX_TURN_DURATION_SECONDS}s)，已停止"
        return False, ""

    def before_tool(self, tool_name: str, tool_args_str: str) -> tuple[bool, str]:
        if self.waiting_for_terminal_feedback and tool_name in COMMAND_TOOL_NAMES:
            return True, "命令已发送，等待终端反馈，当前轮已停止"

        self.tool_call_count += 1
        if self.tool_call_count > MAX_TOOL_CALLS:
            return True, f"当前轮工具调用次数超过限制 ({MAX_TOOL_CALLS})，已停止"

        if tool_name != READ_LOG_TOOL_NAME:
            normalized_args = (tool_args_str or "").strip().replace("\n", " ")[:256]
            step_token = f"{tool_name}:{normalized_args}"
            self.recent_steps.append(step_token)
            if len(self.recent_steps) >= LOOP_THRESHOLD:
                recent = list(self.recent_steps)[-LOOP_THRESHOLD:]
                if all(token == step_token for token in recent):
                    return True, f"检测到重复动作循环: {tool_name}"


        return False, ""

    def record_progress(self, progress_token: str | None) -> tuple[bool, str]:
        if not progress_token:
            self.no_progress_steps += 1
        elif progress_token == self.last_progress_token:
            self.no_progress_steps += 1
        else:
            self.last_progress_token = progress_token
            self.no_progress_steps = 0

        if self.no_progress_steps >= MAX_NO_PROGRESS_STEPS:
            return True, "连续多步没有新进展，当前轮已停止"

        return False, ""

    def after_tool(self, tool_name: str, result_text: str) -> tuple[bool, str]:
        if tool_name in COMMAND_TOOL_NAMES:
            self.waiting_for_terminal_feedback = True
            return True, "命令已发送，等待终端反馈"

        normalized_result = result_text.strip()
        result_fingerprint = hashlib.sha1(normalized_result[:4000].encode("utf-8")).hexdigest()

        if tool_name == READ_LOG_TOOL_NAME:
            if result_fingerprint == self.last_log_fingerprint:
                self.repeated_log_reads += 1
            else:
                self.last_log_fingerprint = result_fingerprint
                self.repeated_log_reads = 0

            if self.repeated_log_reads >= MAX_REPEATED_LOG_READS:
                return True, "日志没有新内容，当前轮已停止，请基于已有终端输出总结结果。"

            return self.record_progress(f"log:{result_fingerprint}")

        return self.record_progress(f"{tool_name}:{result_fingerprint}")


@dataclass
class PendingCommand:
    tool_name: str
    command: str
    normalized_command: str
    log_line_cursor: int = 0
    dispatched_at: datetime = field(default_factory=datetime.now)
    echo_count: int = 0
    timeout_warned: bool = False
    input_mode: str | None = None


@dataclass
class TerminalInputContext:
    command: str
    normalized_command: str
    input_mode: str
    created_at: datetime = field(default_factory=datetime.now)
    last_seen_at: datetime = field(default_factory=datetime.now)


@dataclass
class TerminalAnalysisResult:
    content: str | None
    terminal_source: str
    direct_response: bool = False


class AgentSession:
    def __init__(self, item_id: str, handler_id: str):
        self.item_id = item_id
        self.handler_id = handler_id
        self.agent: Agent | None = None
        self.state = SessionState.IDLE
        self.input_queue: queue.Queue[InputMessage] = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self.output_callbacks: list[Callable] = []
        self.lock = threading.RLock()
        self._abort_flag = False
        self._last_activity = datetime.now()
        self._current_turn_id: str | None = None
        self._last_status_signature: tuple[str, str, str] | None = None
        self._pending_command: PendingCommand | None = None
        self._pending_command_recheck_timer: threading.Timer | None = None
        self._terminal_input_context: TerminalInputContext | None = None

        logger.info(f"[AgentSession] Created session for item={item_id}, handler={handler_id}")

    def get_agent(self) -> Agent | None:
        try:
            from sqlmodel import Session

            from app.core.db import engine
            from app.models import ItemHandler

            with Session(engine) as session:
                handler = session.get(ItemHandler, self.handler_id)
                if handler:
                    self.agent = agent_manager.get_or_create(handler)
                    logger.debug(f"[AgentSession] Refreshed agent for handler {self.handler_id}")
                    return self.agent
        except Exception as exc:
            logger.error(f"[AgentSession] Failed to get agent: {exc}")

        return self.agent

    def add_output_callback(self, callback: Callable):
        with self.lock:
            if callback not in self.output_callbacks:
                self.output_callbacks.append(callback)

    def remove_output_callback(self, callback: Callable):
        with self.lock:
            if callback in self.output_callbacks:
                self.output_callbacks.remove(callback)

    def _broadcast_event(self, event: dict[str, Any]):
        with self.lock:
            callbacks = self.output_callbacks.copy()

        for callback in callbacks:
            try:
                callback(event)
            except Exception as exc:
                logger.error(f"[AgentSession] Error in output callback: {exc}")

    def emit_output(
        self,
        message: str,
        msg_type: str = "agent_response",
        extra: dict[str, Any] | None = None,
        *,
        persist: bool = True,
    ):
        if not message:
            return

        event: dict[str, Any] = {
            "type": msg_type,
            "content": message,
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            event.update(extra)

        if persist:
            try:
                append_chat_message(
                    self.item_id,
                    role=None,
                    content=message,
                    message_type=msg_type,
                    timestamp=event["timestamp"],
                    extra=extra,
                )
            except Exception as exc:
                logger.error(f"[AgentSession] Failed to persist output: {exc}")

        self._broadcast_event(event)

    def emit_status(
        self,
        status: str,
        content: str | None = None,
        extra: dict[str, Any] | None = None,
    ):
        payload = content if content is not None else ""
        extra_signature = ""
        if extra:
            try:
                extra_signature = json.dumps(extra, sort_keys=True, ensure_ascii=False)
            except TypeError:
                extra_signature = str(sorted(extra.items()))
        signature = (status, payload, extra_signature)
        if signature == self._last_status_signature:
            return

        self._last_status_signature = signature
        event: dict[str, Any] = {
            "type": "agent_status",
            "status": status,
            "content": payload,
            "timestamp": datetime.now().isoformat(),
        }
        if self._current_turn_id:
            event["turn_id"] = self._current_turn_id
        if extra:
            event.update(extra)
        self._broadcast_event(event)

    def _emit_collecting_terminal_status(self):
        self.emit_status(
            "collecting",
            "\u63a5\u6536\u8fc7\u6ee4\u540e\u7ec8\u7aef\u8f93\u51fa\u4e2d",
            {"terminal_source": TERMINAL_SOURCE_FILTERED},
        )

    def _emit_running_terminal_status(self, terminal_source: str):
        if terminal_source == TERMINAL_SOURCE_RAW_FEEDBACK:
            content = "\u5206\u6790\u547d\u4ee4\u539f\u751f\u65e5\u5fd7\u53cd\u9988\u4e2d"
        else:
            content = "\u5206\u6790\u8fc7\u6ee4\u540e\u7ec8\u7aef\u8f93\u51fa\u4e2d"

        self.emit_status(
            "running",
            content,
            {"terminal_source": terminal_source},
        )

    def _emit_waiting_terminal_status(self, tool_name: str | None = None):
        extra = {"terminal_source": TERMINAL_SOURCE_RAW_FEEDBACK}
        if tool_name:
            extra["tool_name"] = tool_name
        self.emit_status(
            "waiting_terminal",
            "\u547d\u4ee4\u5df2\u53d1\u9001\uff0c\u8bfb\u53d6\u539f\u751f\u65e5\u5fd7\u53cd\u9988\u4e2d",
            extra,
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join((value or "").strip().split()).lower()

    @staticmethod
    def _strip_timestamp_prefix(line: str) -> str:
        return re.sub(r"^\[[^\]]+\]\s*", "", line or "").strip()

    def _extract_command_text(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        for key in ("command", "cmd", "text"):
            value = tool_args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return f"{tool_name}: {json.dumps(tool_args, ensure_ascii=False, sort_keys=True)}"

    def _short_command(self, command: str, *, max_length: int = 120) -> str:
        compact = " ".join((command or "").strip().split())
        if len(compact) <= max_length:
            return compact
        return compact[: max_length - 1] + "…"

    def _set_terminal_input_context(self, command: str, input_mode: str | None) -> None:
        if input_mode != TERMINAL_INPUT_MODE_CONSOLE:
            return
        context = TerminalInputContext(
            command=command,
            normalized_command=self._normalize_text(command),
            input_mode=input_mode,
        )
        with self.lock:
            self._terminal_input_context = context

    def _clear_terminal_input_context_for_command(self, command: str) -> None:
        normalized_command = self._normalize_text(command)
        with self.lock:
            context = self._terminal_input_context
            if context and context.normalized_command == normalized_command:
                self._terminal_input_context = None

    def _get_terminal_input_context(self) -> TerminalInputContext | None:
        with self.lock:
            context = self._terminal_input_context
            if not context:
                return None
            age_seconds = (datetime.now() - context.last_seen_at).total_seconds()
            if age_seconds > TERMINAL_INPUT_CONTEXT_TTL_SECONDS:
                self._terminal_input_context = None
                return None
            return context

    def _validate_terminal_command_input(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> str | None:
        if tool_name != EXECUTE_COMMAND_TOOL_NAME:
            return None

        command = self._extract_command_text(tool_name, tool_args)
        context = self._get_terminal_input_context()
        if context and context.input_mode == TERMINAL_INPUT_MODE_CONSOLE:
            if is_terminal_console_command(command):
                with self.lock:
                    active_context = self._terminal_input_context
                    if active_context:
                        active_context.last_seen_at = datetime.now()
                return None
            return (
                f"终端当前在 `{self._short_command(context.command)}` 的交互式控制台中。"
                f"`{self._short_command(command)}` 看起来是 shell 命令，发送进去不会由 shell 执行，已拦截。"
            )

        pending = self._get_pending_command()
        if not pending:
            return None

        if pending.input_mode == TERMINAL_INPUT_MODE_BUSY:
            return (
                f"终端正在执行 `{self._short_command(pending.command)}`，这个前台进程通常不接收新的 shell 命令。"
                f"已拦截 `{self._short_command(command)}`，请等待当前任务结束或先中断。"
            )

        if pending.input_mode == TERMINAL_INPUT_MODE_CONSOLE:
            if is_terminal_console_command(command):
                return None
            return (
                f"终端正在启动 `{self._short_command(pending.command)}` 的交互式控制台。"
                f"`{self._short_command(command)}` 看起来不是控制台命令，已拦截。"
            )

        return None

    def _set_pending_command(self, tool_name: str, tool_args: dict[str, Any]):
        command = self._extract_command_text(tool_name, tool_args)
        input_mode = classify_terminal_input_mode(command)
        pending = PendingCommand(
            tool_name=tool_name,
            command=command,
            normalized_command=self._normalize_text(command),
            log_line_cursor=self._get_log_line_count(),
            input_mode=input_mode,
        )
        self._set_terminal_input_context(command, input_mode)
        with self.lock:
            self._pending_command = pending
        self._schedule_pending_command_recheck()

    def _clear_pending_command(self):
        self._cancel_pending_command_recheck()
        with self.lock:
            self._pending_command = None

    def _get_pending_command(self) -> PendingCommand | None:
        with self.lock:
            return self._pending_command

    def has_pending_command(self) -> bool:
        return self._get_pending_command() is not None

    def _cancel_pending_command_recheck(self):
        with self.lock:
            timer = self._pending_command_recheck_timer
            self._pending_command_recheck_timer = None

        if timer:
            timer.cancel()

    def _schedule_pending_command_recheck(
        self,
        delay_seconds: float = PENDING_COMMAND_RECHECK_SECONDS,
    ):
        pending = self._get_pending_command()
        if not pending or self._abort_flag:
            return

        with self.lock:
            if self._pending_command_recheck_timer:
                self._pending_command_recheck_timer.cancel()

            timer = threading.Timer(
                delay_seconds,
                self._run_pending_command_recheck,
                args=(pending.normalized_command,),
            )
            timer.daemon = True
            self._pending_command_recheck_timer = timer

        timer.start()

    def _build_missing_command_feedback(self, pending: PendingCommand) -> str:
        return (
            f"命令 `{pending.command}` 已发送，但在 "
            f"{PENDING_COMMAND_TIMEOUT_SECONDS} 秒内没有读取到新的原生日志反馈。"
        )

    def _run_pending_command_recheck(self, expected_command: str):
        with self.lock:
            self._pending_command_recheck_timer = None

        pending = self._get_pending_command()
        if (
            not pending
            or pending.normalized_command != expected_command
            or self._abort_flag
        ):
            return

        if self.is_running_turn() or not self.input_queue.empty():
            self._schedule_pending_command_recheck()
            return

        elapsed_seconds = (datetime.now() - pending.dispatched_at).total_seconds()
        current_log_line_count = self._get_log_line_count()
        has_new_log_lines = current_log_line_count > pending.log_line_cursor
        should_force_tail_check = (
            pending.echo_count > 0
            and elapsed_seconds >= PENDING_COMMAND_STALLED_CONFIRM_SECONDS
        )

        if not has_new_log_lines and not should_force_tail_check:
            if elapsed_seconds >= PENDING_COMMAND_TIMEOUT_SECONDS:
                logger.warning(
                    "[AgentSession] Pending command timed out without raw feedback for item=%s, command=%s",
                    self.item_id,
                    pending.command,
                )
                self._clear_pending_command()
                self.emit_output(
                    self._build_missing_command_feedback(pending),
                    "agent_warning",
                    {"tool_name": pending.tool_name},
                )
                return

            self._schedule_pending_command_recheck()
            return

        logger.info(
            "[AgentSession] Triggering pending command recheck for item=%s, command=%s, new_lines=%s, echo_count=%s",
            self.item_id,
            pending.command,
            has_new_log_lines,
            pending.echo_count,
        )
        self.process_input(
            InputMessage(
                input_type=InputType.TERMINAL,
                content="",
                raw_content="",
            )
        )
        if self.has_pending_command():
            self._schedule_pending_command_recheck()

    def _get_log_manager(self):
        from app.services.log_manager import LogManager

        return LogManager()

    def _get_log_line_count(self) -> int:
        try:
            return self._get_log_manager().get_line_count(self.item_id)
        except Exception as exc:
            logger.debug(
                "[AgentSession] Failed to read log line count for item=%s: %s",
                self.item_id,
                exc,
            )
            return 0

    def _consume_pending_log_delta(self) -> str:
        pending = self._get_pending_command()
        if not pending:
            return ""

        try:
            log_manager = self._get_log_manager()
            delta = log_manager.get_lines_since(self.item_id, pending.log_line_cursor) or ""
            new_cursor = log_manager.get_line_count(self.item_id)
        except Exception as exc:
            logger.debug(
                "[AgentSession] Failed to consume pending log delta for item=%s: %s",
                self.item_id,
                exc,
            )
            return ""

        with self.lock:
            current_pending = self._pending_command
            if current_pending and current_pending.normalized_command == pending.normalized_command:
                current_pending.log_line_cursor = new_cursor

        return delta

    def _get_recent_pending_log_tail(self, lines: int = 8) -> str:
        try:
            return self._get_log_manager().get_last_lines(self.item_id, lines) or ""
        except Exception as exc:
            logger.debug(
                "[AgentSession] Failed to read recent log tail for item=%s: %s",
                self.item_id,
                exc,
            )
            return ""

    def _resolve_terminal_analysis_content(
        self,
        input_msg: InputMessage,
    ) -> TerminalAnalysisResult:
        pending = self._get_pending_command()
        if pending:
            analysis_content = self._consume_pending_log_delta().strip()
            if not analysis_content:
                analysis_content = self._get_recent_pending_log_tail().strip()
            if not analysis_content:
                analysis_content = (input_msg.raw_content or input_msg.content).strip()

            if not analysis_content:
                return TerminalAnalysisResult(
                    content=None,
                    terminal_source=TERMINAL_SOURCE_RAW_FEEDBACK,
                )

            should_hold, resolved_feedback, direct_response = (
                self._maybe_hold_for_pending_terminal_feedback(analysis_content)
            )
            if should_hold:
                return TerminalAnalysisResult(
                    content=None,
                    terminal_source=TERMINAL_SOURCE_RAW_FEEDBACK,
                )
            if resolved_feedback:
                return TerminalAnalysisResult(
                    content=resolved_feedback,
                    terminal_source=TERMINAL_SOURCE_RAW_FEEDBACK,
                    direct_response=direct_response,
                )

            return TerminalAnalysisResult(
                content=analysis_content,
                terminal_source=TERMINAL_SOURCE_RAW_FEEDBACK,
            )

        analysis_content = (input_msg.content or "").strip()
        return TerminalAnalysisResult(
            content=analysis_content or None,
            terminal_source=TERMINAL_SOURCE_FILTERED,
        )

    def _is_prompt_only_line(self, line: str) -> bool:
        normalized_line = self._normalize_text(self._strip_timestamp_prefix(line))
        if not normalized_line:
            return True
        if re.fullmatch(r"[#>$\s]+", normalized_line):
            return True
        if normalized_line.endswith(("#", "$", ">")) and any(
            marker in normalized_line for marker in "#$>"
        ):
            return bool(re.fullmatch(r"[\w\s./:@~()\\\-\[\]#>$]+", normalized_line))
        return False

    def _is_command_echo_line(self, line: str, pending: PendingCommand) -> bool:
        normalized_line = self._normalize_text(self._strip_timestamp_prefix(line))
        if not normalized_line:
            return False
        if normalized_line == pending.normalized_command:
            return True

        stripped_prompt_line = re.sub(r"^(?:[#>$]\s*)+", "", normalized_line).strip()
        if stripped_prompt_line == pending.normalized_command:
            return True

        if normalized_line.endswith(pending.normalized_command):
            prefix = normalized_line[: -len(pending.normalized_command)]
            if any(marker in prefix for marker in "#$>") and re.fullmatch(
                r"[\w\s./:@~()\\\-\[\]#>$]*",
                prefix,
            ):
                return True

        return False

    def _build_empty_command_feedback(self, pending: PendingCommand) -> str:
        return f"命令 `{pending.command}` 已执行完成，终端没有输出内容。"

    def _maybe_resolve_empty_command_feedback(
        self,
        pending: PendingCommand,
        lines: list[str],
        informative_lines: list[str],
    ) -> str | None:
        prompt_only_count = len(lines) - len(informative_lines)
        tail_text = self._get_recent_pending_log_tail()
        tail_lines = [line for line in tail_text.splitlines() if line.strip()]
        tail_informative_lines = [
            line for line in tail_lines if not self._is_prompt_only_line(line)
        ]
        tail_prompt_only_count = len(tail_lines) - len(tail_informative_lines)
        tail_echo_count = sum(
            1 for line in tail_informative_lines if self._is_command_echo_line(line, pending)
        )
        with self.lock:
            current_pending = self._pending_command
            prior_echo_count = (
                current_pending.echo_count
                if current_pending
                and current_pending.normalized_command == pending.normalized_command
                else 0
            )

        # Prompt has returned or the same echo has appeared repeatedly: treat as
        # a completed command with empty stdout/stderr instead of waiting forever.
        if (
            prompt_only_count > 0
            or tail_prompt_only_count > 0
            or len(informative_lines) > 1
            or tail_echo_count > 1
            or prior_echo_count > 0
        ):
            logger.info(
                "[AgentSession] Treating empty command output as completed for item=%s, command=%s",
                self.item_id,
                pending.command,
            )
            self._clear_pending_command()
            return self._build_empty_command_feedback(pending)

        return None

    def _maybe_hold_for_pending_terminal_feedback(
        self,
        content: str,
    ) -> tuple[bool, str | None, bool]:
        pending = self._get_pending_command()
        if not pending:
            return False, None, False

        lines = [line for line in content.splitlines() if line.strip()]
        informative_lines = [line for line in lines if not self._is_prompt_only_line(line)]
        if not informative_lines:
            logger.info(
                "[AgentSession] Prompt returned without command output for item=%s, command=%s",
                self.item_id,
                pending.command,
            )
            self._clear_pending_command()
            return False, self._build_empty_command_feedback(pending), True

        if not all(self._is_command_echo_line(line, pending) for line in informative_lines):
            logger.info(
                "[AgentSession] Received non-echo terminal feedback for item=%s, command=%s",
                self.item_id,
                pending.command,
            )
            if pending.input_mode == TERMINAL_INPUT_MODE_BUSY:
                if len(lines) > len(informative_lines):
                    self._clear_pending_command()
                return False, None, False
            if pending.input_mode == TERMINAL_INPUT_MODE_CONSOLE:
                self._set_terminal_input_context(pending.command, pending.input_mode)
            self._clear_pending_command()
            return False, None, False

        resolved_feedback = self._maybe_resolve_empty_command_feedback(
            pending,
            lines,
            informative_lines,
        )
        if resolved_feedback:
            return False, resolved_feedback, True

        warning_text: str | None = None
        with self.lock:
            current_pending = self._pending_command
            if current_pending and current_pending.normalized_command == pending.normalized_command:
                current_pending.echo_count += len(informative_lines)
                if (
                    not current_pending.timeout_warned
                    and (
                        datetime.now() - current_pending.dispatched_at
                    ).total_seconds()
                    > PENDING_COMMAND_TIMEOUT_SECONDS
                ):
                    current_pending.timeout_warned = True
                    warning_text = (
                        f"等待终端反馈超时，当前只收到命令回显：{current_pending.command}"
                    )

        logger.info(
            "[AgentSession] Suppressed echoed command for item=%s, command=%s",
            self.item_id,
            pending.command,
        )
        if warning_text:
            self.emit_output(
                warning_text,
                "agent_warning",
                {"tool_name": pending.tool_name},
            )
        self._emit_waiting_terminal_status(pending.tool_name)
        return True, None, False

    def _emit_idle_or_waiting_status(self, queue_size: int):
        if queue_size > 0:
            self.emit_status("queued", "后续输出排队中", {"queue_size": queue_size})
            return

        pending = self._get_pending_command()
        if pending:
            self._emit_waiting_terminal_status(pending.tool_name)
            return

        self.emit_status("idle", "")

    def mark_collecting(self):
        with self.lock:
            if self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}:
                return
            self.state = SessionState.COLLECTING
        self._emit_collecting_terminal_status()

    def mark_waiting_terminal_feedback(self):
        pending = self._get_pending_command()
        self._emit_waiting_terminal_status(pending.tool_name if pending else None)

    @staticmethod
    def _merge_text_parts(existing: str, incoming: str) -> str:
        left = (existing or "").strip("\n")
        right = (incoming or "").strip("\n")
        if left and right:
            return f"{left}\n{right}"
        return left or right

    def _merge_terminal_queue_input(self, input_msg: InputMessage) -> bool:
        queued_items = getattr(self.input_queue, "queue", None)
        if not queued_items:
            return False

        last_item = queued_items[-1]
        if not isinstance(last_item, InputMessage):
            return False
        if last_item.input_type != InputType.TERMINAL:
            return False

        last_item.content = self._merge_text_parts(last_item.content, input_msg.content)
        last_item.raw_content = self._merge_text_parts(
            last_item.raw_content,
            input_msg.raw_content,
        )
        if input_msg.query:
            last_item.query = self._merge_text_parts(last_item.query, input_msg.query)
        if input_msg.callback:
            last_item.callback = input_msg.callback
        last_item.timestamp = input_msg.timestamp
        return True

    def queue_input(self, input_msg: InputMessage) -> bool:
        with self.lock:
            try:
                merged = False
                if input_msg.input_type == InputType.TERMINAL:
                    merged = self._merge_terminal_queue_input(input_msg)

                if not merged:
                    self.input_queue.put_nowait(input_msg)
                queue_size = self.input_queue.qsize()
                logger.info(
                    f"[AgentSession] {'Merged' if merged else 'Queued'} "
                    f"{input_msg.input_type.value} input for item {self.item_id}, "
                    f"queue size: {queue_size}"
                )
            except queue.Full:
                logger.warning(f"[AgentSession] Input queue full for item {self.item_id}")
                self.emit_output("输入队列已满，后续输入已丢弃", "agent_warning")
                return False

        if input_msg.input_type == InputType.TERMINAL:
            terminal_source = (
                TERMINAL_SOURCE_RAW_FEEDBACK
                if self.has_pending_command() and (input_msg.raw_content or "").strip()
                else TERMINAL_SOURCE_FILTERED
            )
            self.emit_status(
                "queued",
                "后续命令反馈排队中"
                if terminal_source == TERMINAL_SOURCE_RAW_FEEDBACK
                else "后续过滤终端输出排队中",
                {
                    "queue_size": self.input_queue.qsize(),
                    "terminal_source": terminal_source,
                },
            )
        else:
            self.emit_status("queued", "消息已排队，等待当前轮结束", {"queue_size": self.input_queue.qsize()})

        return True

    def clear_queued_inputs(self) -> int:
        cleared = 0
        while True:
            try:
                self.input_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        return cleared

    def _begin_turn(self, input_msg: InputMessage):
        with self.lock:
            self.state = SessionState.RUNNING
            self._abort_flag = False
            self._current_turn_id = uuid4().hex[:8]

        if input_msg.input_type == InputType.TERMINAL:
            terminal_source = (
                TERMINAL_SOURCE_RAW_FEEDBACK
                if self.has_pending_command()
                else TERMINAL_SOURCE_FILTERED
            )
            self._emit_running_terminal_status(terminal_source)
        else:
            self.emit_status("running", "回复中")

    def _finish_turn(self):
        with self.lock:
            queue_size = self.input_queue.qsize()
            self.state = SessionState.IDLE if queue_size == 0 else SessionState.COOLDOWN
            self._current_turn_id = None
        self._emit_idle_or_waiting_status(queue_size)
        return

        if queue_size > 0:
            self.emit_status("queued", "后续输出排队中", {"queue_size": queue_size})
        else:
            self.emit_status("idle", "")

    def process_queue(self):
        while True:
            try:
                input_msg = self.input_queue.get(timeout=1)
            except queue.Empty:
                with self.lock:
                    self.state = SessionState.IDLE
                self._emit_idle_or_waiting_status(0)
                return
                self.emit_status("idle", "")
                return

            if (datetime.now() - input_msg.timestamp).total_seconds() > 60:
                logger.debug(f"[AgentSession] Skipping stale input for item {self.item_id}")
                continue

            self._begin_turn(input_msg)

            try:
                self._process_input(input_msg)
            except Exception as exc:
                logger.error(f"[AgentSession] Error processing queue: {exc}")
                self.emit_output(f"处理失败: {exc}", "agent_error")
            finally:
                self._finish_turn()

    def process_input(self, input_msg: InputMessage):
        with self.lock:
            if self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}:
                self.queue_input(input_msg)
                return

        self._begin_turn(input_msg)

        try:
            self._process_input(input_msg)
        finally:
            self._finish_turn()

            if not self.input_queue.empty():
                threading.Thread(target=self.process_queue, daemon=True).start()

    def _process_input(self, input_msg: InputMessage):
        agent = self.get_agent()
        if not agent:
            self.emit_output("Agent 不可用", "agent_error")
            return

        self._last_activity = datetime.now()

        if input_msg.input_type == InputType.TERMINAL:
            self._process_terminal_input(input_msg, agent)
        else:
            self._process_chat_input(input_msg, agent)

    def _process_terminal_input(self, input_msg: InputMessage, agent: Agent):
        if input_msg.content:
            self.emit_output(input_msg.content, "terminal_output")

        analysis = self._resolve_terminal_analysis_content(input_msg)
        if not analysis.content:
            return
        if analysis.direct_response:
            self.emit_output(analysis.content, "agent_response")
            return

        transient_integration_tools_added = False
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(agent.start_mcp_servers())
            if (
                is_critical_terminal_event(analysis.content)
                and should_enable_terminal_alert_integrations(agent, analysis.content)
            ):
                transient_integration_tools_added = bool(
                    loop.run_until_complete(
                        ensure_terminal_alert_integration_tools(
                            agent,
                            analysis.content,
                        )
                    )
                )

            messages = self._build_terminal_messages(
                agent,
                input_msg,
                analysis.content,
                terminal_source=analysis.terminal_source,
            )
            extract_integration_context_targets(agent, messages)
            turn_guard = TurnGuard()
            self._current_turn_id = turn_guard.turn_id
            self._emit_running_terminal_status(analysis.terminal_source)

            for _ in range(MAX_ITERATIONS):
                timed_out, timeout_reason = turn_guard.check_timeout()
                if timed_out:
                    self.emit_output(timeout_reason, "agent_warning")
                    break

                if self._abort_flag:
                    self.emit_output("当前轮已中断", "agent_warning")
                    self.emit_status("interrupted", "当前轮已中断")
                    break

                response = self._call_llm(agent, messages)
                message = response.choices[0].message

                if not (hasattr(message, "tool_calls") and message.tool_calls):
                    if message.content:
                        final_content = guard_ungrounded_tool_claim(
                            message.content,
                            tool_called=turn_guard.tool_call_count > 0,
                        )
                        self.emit_output(final_content, "agent_response")
                    break

                next_messages = self._handle_tool_calls(
                    agent,
                    loop,
                    messages,
                    message,
                    turn_guard,
                    terminal_source=analysis.terminal_source,
                )
                if next_messages is None:
                    break
                messages = next_messages

            if transient_integration_tools_added:
                clear_terminal_alert_integration_tools(agent)
            loop.close()
        except Exception as exc:
            logger.error(f"[AgentSession] Terminal processing error: {exc}")
            self.emit_output(f"处理失败: {exc}", "agent_error")

            if transient_integration_tools_added:
                clear_terminal_alert_integration_tools(agent)
            if loop is not None and not loop.is_closed():
                loop.close()

    def _process_chat_input(self, input_msg: InputMessage, agent: Agent):
        if input_msg.callback:
            self.add_output_callback(input_msg.callback)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(agent.start_mcp_servers())

            messages = self._build_chat_messages(agent, input_msg)
            turn_guard = TurnGuard()
            self._current_turn_id = turn_guard.turn_id
            self.emit_status("running", "回复中")

            for _ in range(MAX_ITERATIONS):
                timed_out, timeout_reason = turn_guard.check_timeout()
                if timed_out:
                    self.emit_output(timeout_reason, "agent_warning")
                    break

                if self._abort_flag:
                    self.emit_output("当前轮已中断", "agent_warning")
                    self.emit_status("interrupted", "当前轮已中断")
                    break

                response = self._call_llm(agent, messages)
                message = response.choices[0].message

                if not (hasattr(message, "tool_calls") and message.tool_calls):
                    if message.content:
                        final_content = guard_ungrounded_tool_claim(
                            message.content,
                            tool_called=turn_guard.tool_call_count > 0,
                        )
                        self.emit_output(final_content, "agent_response")
                    break

                next_messages = self._handle_tool_calls(agent, loop, messages, message, turn_guard)
                if next_messages is None:
                    break
                messages = next_messages

            loop.close()
        except Exception as exc:
            logger.error(f"[AgentSession] Chat processing error: {exc}")
            self.emit_output(f"处理失败: {exc}", "agent_error")

    def _build_terminal_messages(
        self,
        agent: Agent,
        input_msg: InputMessage,
        terminal_content: str | None = None,
        *,
        terminal_source: str = TERMINAL_SOURCE_FILTERED,
    ) -> list[dict]:
        effective_terminal_content = terminal_content or input_msg.content
        pending_command = self._get_pending_command()
        return build_terminal_turn_messages(
            agent,
            item_id=self.item_id,
            terminal_content=effective_terminal_content,
            query=(input_msg.query or effective_terminal_content or "")[:500],
            terminal_source=terminal_source,
            pending_command=pending_command.command if pending_command else "",
        )

    def _build_chat_messages(self, agent: Agent, input_msg: InputMessage) -> list[dict]:
        return build_chat_turn_messages(
            agent,
            item_id=self.item_id,
            message=input_msg.content,
            query=input_msg.query or input_msg.content,
        )

    def _get_skill_prompt(
        self,
        agent: Agent,
        query: str = "",
        *,
        skill_query: str | None = None,
    ) -> str:
        prompt_parts = [get_system_prompt(agent)]

        effective_skill_query = skill_query if skill_query is not None else query
        skills = agent.match_skills(effective_skill_query) if effective_skill_query else []
        for skill in skills:
            if skill.category == "system":
                continue
            if skill.action and skill.action.prompt:
                prompt_parts.append(skill.action.prompt)

        base_prompt = "\n\n".join(part.strip() for part in prompt_parts if part and part.strip())
        if query:
            return f"{base_prompt}\n\nUser query: {query}"
        return base_prompt

    def _get_relevant_memories(self, query: str, n_results: int = 3) -> str:
        try:
            from app.services.agent.memory.vector_store import vector_store

            memories = vector_store.search_memories(
                item_id=self.item_id,
                query=query,
                n_results=n_results,
            )
            if not memories:
                return ""

            return "\n".join([f"- {memory['content']}" for memory in memories])
        except Exception as exc:
            logger.warning(f"[AgentSession] Failed to retrieve memories: {exc}")
            return ""

    def _query_matches_tool(self, query: str, tool_name: str) -> bool:
        tool_base = tool_name.replace("mcp_local_", "").replace("_", " ")
        return tool_base in query.lower()

    def _should_hide_tool_details(self, tool_name: str) -> bool:
        return tool_name in SILENT_TOOL_NAMES

    def _call_llm(self, agent: Agent, messages: list[dict]):
        kwargs: dict[str, Any] = {
            "model": agent._context.model,
            "messages": messages,
            "timeout": REQUEST_TIMEOUT,
            "temperature": 0.1,
        }

        if agent._context.api_key:
            kwargs["api_key"] = agent._context.api_key
        if agent._context.api_url:
            kwargs["api_base"] = agent._context.api_url

        if tools := agent.get_tools_for_litellm():
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return completion(**kwargs)

    def _handle_tool_calls(
        self,
        agent: Agent,
        loop: asyncio.AbstractEventLoop,
        messages: list[dict],
        message: Any,
        turn_guard: TurnGuard,
        terminal_source: str | None = None,
    ) -> list[dict] | None:
        tool_calls = list(message.tool_calls or [])
        if tool_calls:
            if terminal_source:
                self._emit_running_terminal_status(terminal_source)
            else:
                self.emit_status("running", "回复中")

        assistant_message = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [],
        }
        tool_messages: list[dict[str, Any]] = []

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            tool_args_str = tool_call.function.arguments

            should_stop, reason = turn_guard.before_tool(tool_name, tool_args_str)
            if should_stop:
                self.emit_output(reason, "agent_warning", {"tool_name": tool_name})
                return None

            try:
                tool_args = parse_tool_arguments(tool_name, tool_args_str)
            except ToolArgumentParseError:
                logger.error(
                    "[AgentSession] Failed to parse tool args for %s: %r",
                    tool_name,
                    tool_args_str,
                )
                self.emit_output(
                    f"工具参数解析失败: {tool_name}",
                    "agent_error",
                    {"tool_name": tool_name},
                )
                return None

            normalized_tool_args_str = json.dumps(tool_args, ensure_ascii=False)
            tool_args["item_id"] = self.item_id
            terminal_input_error = self._validate_terminal_command_input(tool_name, tool_args)
            if terminal_input_error:
                self.emit_output(
                    terminal_input_error,
                    "agent_warning",
                    {"tool_name": tool_name},
                )
                return None
            hide_tool_details = self._should_hide_tool_details(tool_name)

            if hide_tool_details:
                self.emit_status("tool", "读取日志中", {"tool_name": tool_name})
            else:
                self.emit_status("tool", f"调用工具：{tool_name}", {"tool_name": tool_name})
                self.emit_output(
                    f"执行工具: {tool_name}",
                    "agent_action",
                    {"tool_name": tool_name},
                )

            result = loop.run_until_complete(agent.execute_tool(tool_name, tool_args))
            logger.info(f"[AgentSession] Tool {tool_name} executed")

            result_text = self._format_tool_result(result).strip()
            command_dispatch_failed = is_command_dispatch_failure_result(tool_name, result_text)
            if result_text and not hide_tool_details:
                self.emit_output(
                    result_text,
                    "agent_tool_result",
                    {"tool_name": tool_name},
                )

            if command_dispatch_failed:
                self.emit_output(
                    COMMAND_DISPATCH_FAILURE_MESSAGE,
                    "agent_warning",
                    {"tool_name": tool_name},
                )
                return None

            assistant_message["tool_calls"].append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": normalized_tool_args_str,
                    },
                }
            )
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_text,
                }
            )

            should_stop_after_tool, reason_after_tool = turn_guard.after_tool(
                tool_name,
                result_text,
            )
            if tool_name in COMMAND_TOOL_NAMES and result.get("success"):
                self._set_pending_command(tool_name, tool_args)
                self._emit_waiting_terminal_status(tool_name)
                return None

            if should_stop_after_tool:
                self.emit_output(
                    reason_after_tool,
                    "agent_warning",
                    {"tool_name": tool_name},
                )
                return None

        messages.append(assistant_message)
        messages.extend(tool_messages)
        return messages

    def _format_tool_result(self, result: dict) -> str:
        if not isinstance(result, dict):
            return str(result)
        if result.get("success"):
            result_data = result.get("result", [])
            if isinstance(result_data, list):
                texts = [
                    item.get("text", "")
                    for item in result_data
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                return "\n".join(texts)
            return str(result_data)
        return f"Error: {result.get('error', 'Unknown error')}"

    def abort(self, clear_queue: bool = False):
        cleared = 0
        with self.lock:
            self._abort_flag = True
            self._pending_command = None
            if self.state == SessionState.RUNNING:
                self.state = SessionState.INTERRUPTING
            elif clear_queue:
                self.state = SessionState.IDLE
            if clear_queue:
                cleared = self.clear_queued_inputs()
        self._cancel_pending_command_recheck()
        self.emit_status("interrupting", "中断当前轮中")
        if clear_queue and cleared > 0:
            self.emit_output(f"已清空 {cleared} 条排队输入", "agent_warning")
        logger.info(f"[AgentSession] Aborted session for item {self.item_id}")

    def is_idle(self) -> bool:
        with self.lock:
            return self.state == SessionState.IDLE

    def is_running_turn(self) -> bool:
        with self.lock:
            return self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}

    def shutdown(self):
        self._abort_flag = True
        self._cancel_pending_command_recheck()


class AgentSessionManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._sessions: dict[str, AgentSession] = {}
        self._global_lock = threading.RLock()
        logger.info("[AgentSessionManager] Initialized")

    def get_or_create_session(self, item_id: str, handler_id: str) -> AgentSession:
        with self._global_lock:
            if item_id not in self._sessions:
                self._sessions[item_id] = AgentSession(item_id, handler_id)
            return self._sessions[item_id]

    def get_session(self, item_id: str) -> AgentSession | None:
        with self._global_lock:
            return self._sessions.get(item_id)

    def remove_session(self, item_id: str):
        with self._global_lock:
            session = self._sessions.pop(item_id, None)
            if session:
                session.shutdown()
                logger.info(f"[AgentSessionManager] Removed session for item {item_id}")

    def process_terminal_output(self, item_id: str, handler_id: str, output: str, query: str = ""):
        session = self.get_or_create_session(item_id, handler_id)
        input_msg = InputMessage(
            input_type=InputType.TERMINAL,
            content=output,
            query=query,
        )
        session.process_input(input_msg)

    def process_chat_message(
        self,
        item_id: str,
        handler_id: str,
        message: str,
        callback: Callable | None = None,
        query: str = "",
    ):
        session = self.get_or_create_session(item_id, handler_id)
        input_msg = InputMessage(
            input_type=InputType.CHAT,
            content=message,
            query=query,
            callback=callback,
        )
        session.process_input(input_msg)


agent_session_manager = AgentSessionManager()
