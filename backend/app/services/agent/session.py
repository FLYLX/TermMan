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
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from litellm import completion

from app.core.tool_markup import extract_dsml_tool_calls
from app.services.agent.agent import Agent, agent_manager
from app.services.agent.history.chat import append_chat_message
from app.services.agent.integrations import (
    clear_integration_chat_contexts,
    clear_terminal_alert_integration_tools,
    ensure_integration_chat_context_tools,
    ensure_terminal_alert_integration_tools,
    extract_integration_context_targets,
    integration_message_sent,
    send_integration_final_response_fallback,
    setup_integration_chat_contexts,
    should_enable_terminal_alert_integrations,
)
from app.services.agent.pending_context import (
    attach_terminal_feedback_to_pending_continuation,
    build_pending_terminal_continuation_prompt,
    clear_pending_terminal_continuation,
    record_pending_terminal_continuation,
)
from app.services.agent.prompts import builder as prompt_builder
from app.services.agent.prompts.builder import (
    build_chat_turn_messages,
    build_terminal_turn_messages,
    is_critical_terminal_event,
)
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.robot_delivery import (
    ROBOT_QQ_REPLY_EVENT_TYPE,
    ROBOT_SEND_TOOL_NAME,
    robot_reply_event_content,
)
from app.services.agent.task_workflow import task_workflow_manager
from app.services.agent.tool_arguments import (
    ToolArgumentParseError,
    parse_tool_arguments,
)
from app.services.agent.tool_grounding import guard_ungrounded_tool_claim
from app.services.agent.tool_selection import select_tools_for_turn
from app.services.agent.turn_coordinator import agent_turn_coordinator, agent_turn_key
from app.services.llm_completion import build_litellm_completion_kwargs
from app.services.terminal_command_state import terminal_command_state_manager

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
RUN_JOB_TOOL_NAME = "mcp_local_run_job"
AUTO_ROUTED_TO_JOB_MARKER = "auto_routed_execute_command_to_run_job"
BACKGROUND_JOB_STARTED_MARKER = "background_job_started"
PENDING_REPLY_SENT_MARKER = "pending_reply_sent"
BACKGROUND_JOB_STARTED_RESPONSE = (
    "\u540e\u53f0\u4efb\u52a1\u5df2\u542f\u52a8\uff0c"
    "\u5b8c\u6210\u540e\u6211\u4f1a\u6839\u636e\u7ed3\u679c\u7ee7\u7eed\u5904\u7406"
    "\u5e76\u56de\u5230\u5bf9\u5e94\u6765\u6e90\u3002"
)
COMMAND_DISPATCH_PENDING_MARKER = "命令已发送到终端，尚未确认执行结果:"
TERMINAL_INPUT_MODE_BUSY = "busy"
TERMINAL_INPUT_MODE_CONSOLE = "console"
TERMINAL_INPUT_CONTEXT_TTL_SECONDS = 6 * 60 * 60
DAEMON_JOBS_CONTEXT_REFRESH_SECONDS = 3.0
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
    r"\bjava\s+.*@(?:\S*/)?libraries/\S*(?:minecraftforge|forge|fabric|minecraft)\S*/(?:unix_args|win_args)\.txt\b",
    r"^(?:sudo\s+)?(?:(?:bash|sh)\s+)?(?:\./)?(?:run|start|startserver|server)\.sh\b",
    r"\bbedrock_server\b",
    r"^(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|watch)\b",
    r"^(?:vite|next\s+dev|nuxt\s+dev|astro\s+dev)\b",
    r"^(?:python\d*(?:\.\d+)?\s+-m\s+)?(?:http\.server|uvicorn|fastapi)\b",
    r"^(?:uvicorn|hypercorn|gunicorn)\b",
    r"^(?:tail\s+-f|journalctl\s+-f|docker\s+(?:compose\s+)?logs\s+-f|watch\s+)\b",
    r"^(?:bash|sh|zsh|fish|python\d*(?:\.\d+)?|node|deno)\s*$",
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
SILENT_TOOL_NAMES = {
    READ_LOG_TOOL_NAME,
    RUN_JOB_TOOL_NAME,
    "mcp_robot_send_message",
    "mcp_robot_sleep_conversation",
    "mcp_robot_save_memory",
    "mcp_local_send_pending_reply",
}
TERMINAL_SOURCE_FILTERED = "filtered_output"
TERMINAL_SOURCE_RAW_FEEDBACK = "raw_feedback"
MINECRAFT_PLAYER_CHAT_LINE_RE = re.compile(
    r"(?m)^\s*(?:\[[^\]\n]+\]\s*){0,4}"
    r"(?:\[[^\]\n]*INFO[^\]\n]*\]\s*)?"
    r"(?:(?:\[[^\]\n]+\]|[^\n:：]{1,80})[:：]\s*)?"
    r"(?:\[Not Secure\]\s*)?<[^>\n]{1,64}>\s+\S"
)
MINECRAFT_PLAYER_CHAT_CAPTURE_RE = re.compile(
    r"(?m)^.*?<(?P<player>[^>\n]{1,64})>\s+(?P<message>\S.*)$"
)
MINECRAFT_RELAY_COMMAND_RE = re.compile(
    r"^\s*/?(?:(?:minecraft):)?(?:tell|msg|w|whisper)\s+"
    r"(?P<player>[A-Za-z0-9_]{1,64})\s+(?P<question>\S[\s\S]*)$",
    re.IGNORECASE,
)
TERMINAL_NO_REPLY_MARKERS = (
    "[no_terminal_reply]",
    "[no_reply]",
    "[no_qq_reply]",
    "不回复",
    "不用回复",
    "不用回",
    "不打扰",
)


def is_command_dispatch_failure_result(tool_name: str, result_text: str) -> bool:
    if tool_name not in COMMAND_TOOL_NAMES and tool_name != RUN_JOB_TOOL_NAME:
        return False
    return any(marker in (result_text or "") for marker in COMMAND_DISPATCH_FAILURE_MARKERS)


def is_command_dispatch_pending_result(tool_name: str, result_text: str) -> bool:
    return (
        tool_name == EXECUTE_COMMAND_TOOL_NAME
        and COMMAND_DISPATCH_PENDING_MARKER in (result_text or "")
    )


def is_tool_result_auto_routed_to_job(result: Any) -> bool:
    if not isinstance(result, dict) or not result.get("success"):
        return False
    result_data = result.get("result")
    if not isinstance(result_data, list):
        return False
    return any(
        isinstance(item, dict) and bool(item.get(AUTO_ROUTED_TO_JOB_MARKER))
        for item in result_data
    )


def is_background_job_started_result(result: Any) -> bool:
    if not isinstance(result, dict) or not result.get("success"):
        return False
    result_data = result.get("result")
    if not isinstance(result_data, list):
        return False
    return any(
        isinstance(item, dict)
        and (
            bool(item.get(BACKGROUND_JOB_STARTED_MARKER))
            or bool(item.get(AUTO_ROUTED_TO_JOB_MARKER))
        )
        for item in result_data
    )


def is_pending_reply_sent_result(result: Any) -> bool:
    if not isinstance(result, dict) or not result.get("success"):
        return False
    result_data = result.get("result")
    if not isinstance(result_data, list):
        return False
    return any(
        isinstance(item, dict) and bool(item.get(PENDING_REPLY_SENT_MARKER))
        for item in result_data
    )


def _normalize_command_for_routing(command: str) -> str:
    return " ".join((command or "").strip().split()).lower()


def _classification_command_variants(command: str) -> list[str]:
    normalized = _normalize_command_for_routing(command)
    if not normalized:
        return []

    variants = [normalized]
    remainder = normalized
    while True:
        match = re.match(r"^(?:cd|pushd)\s+[^;&|]+\s*(?:&&|;)\s*(.+)$", remainder)
        if not match:
            break
        remainder = match.group(1).strip()
        if not remainder or remainder in variants:
            break
        variants.append(remainder)
    return variants


def classify_terminal_input_mode(command: str) -> str | None:
    variants = _classification_command_variants(command)
    if not variants:
        return None
    if any(
        re.search(pattern, variant)
        for variant in variants
        for pattern in TERMINAL_CONSOLE_COMMAND_PATTERNS
    ):
        return TERMINAL_INPUT_MODE_CONSOLE
    if any(
        re.search(pattern, variant)
        for variant in variants
        for pattern in TERMINAL_BUSY_COMMAND_PATTERNS
    ):
        return TERMINAL_INPUT_MODE_BUSY
    return None


def should_route_command_to_background_job(command: str) -> bool:
    return classify_terminal_input_mode(command) == TERMINAL_INPUT_MODE_BUSY


def should_auto_route_terminal_tool_to_job(tool_name: str, tool_args: dict[str, Any]) -> bool:
    if tool_name != EXECUTE_COMMAND_TOOL_NAME:
        return False
    command = str((tool_args or {}).get("command") or "")
    return should_route_command_to_background_job(command)


def _coerce_timeout_seconds(value: Any, default: int = PENDING_COMMAND_TIMEOUT_SECONDS) -> int:
    if value is None or value == "":
        return default
    try:
        timeout = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(1, min(timeout, 600))


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _normalize_optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def terminal_content_looks_like_server_chat(content: str) -> bool:
    return bool(MINECRAFT_PLAYER_CHAT_LINE_RE.search(content or ""))


def is_terminal_no_reply_intent(content: str) -> bool:
    normalized = " ".join((content or "").strip().lower().split())
    if not normalized:
        return True
    return len(normalized) <= 120 and any(
        marker.lower() in normalized for marker in TERMINAL_NO_REPLY_MARKERS
    )


def agent_has_litellm_tool(agent: Agent, tool_name: str) -> bool:
    try:
        tools = agent.get_tools_for_litellm()
    except Exception:
        return False
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and function.get("name") == tool_name:
            return True
    return False


def should_retry_terminal_source_delivery(
    *,
    agent: Agent,
    terminal_content: str,
    terminal_source: str,
    final_response: str,
    retry_used: bool,
) -> bool:
    if retry_used or terminal_source != TERMINAL_SOURCE_FILTERED:
        return False
    if is_terminal_no_reply_intent(final_response):
        return False
    if not terminal_content_looks_like_server_chat(terminal_content):
        return False
    return agent_has_litellm_tool(agent, EXECUTE_COMMAND_TOOL_NAME)


def build_terminal_source_delivery_correction_message(final_response: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "终端/服务器来源回复反思：你刚才生成了最终文字，但没有写回消息来源。"
            "当前终端输入像服务器内玩家聊天；如果这段文字是在回答服务器内的人，"
            "现在必须调用 `mcp_local_execute_command` 回到同一个终端。"
            "Minecraft/类 Minecraft 控制台用 `say <回复内容>`，需要私聊玩家时用 `tell <玩家名> <回复内容>`。"
            "只调用工具，不要再次输出普通最终文本。\n"
            f"刚才准备回复的内容:\n{final_response.strip()}"
        ),
    }


class SessionState(Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    COOLDOWN = "cooldown"


class InputType(Enum):
    TERMINAL = "terminal"
    CHAT = "chat"
    SCHEDULED_TASK = "scheduled_task"


@dataclass
class InputMessage:
    input_type: InputType
    content: str
    raw_content: str = ""
    query: str = ""
    reply_ticket_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    callback: Callable | None = None
    completion_callback: Callable[[bool, str], None] | None = None
    scheduled_task_id: str = ""
    scheduled_execution_id: str = ""


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
            return True, f"\u5f53\u524d\u8f6e\u5904\u7406\u8d85\u65f6 ({MAX_TURN_DURATION_SECONDS}s)\uff0c\u5df2\u505c\u6b62"
        return False, ""

    def reset_timeout_window(self) -> None:
        self.started_at = datetime.now()
        self.no_progress_steps = 0

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
    integration_contexts: dict[str, dict[str, Any]] = field(default_factory=dict)
    log_line_cursor: int = 0
    dispatched_at: datetime = field(default_factory=datetime.now)
    echo_count: int = 0
    timeout_warned: bool = False
    input_mode: str | None = None
    expected_output: str = ""
    expected_regex: str = ""
    timeout_seconds: int = PENDING_COMMAND_TIMEOUT_SECONDS
    auto_interrupt_on_timeout: bool = False
    integration_response_sent: bool = False
    reply_ticket_id: str = ""

    def has_expectation(self) -> bool:
        return bool(self.expected_output or self.expected_regex)

    def expectation_label(self) -> str:
        if self.expected_output:
            return self.expected_output
        if self.expected_regex:
            return f"regex:{self.expected_regex}"
        return ""


@dataclass
class TerminalInputContext:
    command: str
    normalized_command: str
    input_mode: str
    created_at: datetime = field(default_factory=datetime.now)
    last_seen_at: datetime = field(default_factory=datetime.now)


@dataclass
class RunningTerminalJob:
    tool_name: str
    command: str
    normalized_command: str
    timeout_seconds: int = 600
    reply_ticket_id: str = ""
    source_type: str = ""
    source_label: str = ""
    started_at: datetime = field(default_factory=datetime.now)


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
        self._running_terminal_job: RunningTerminalJob | None = None
        self._daemon_jobs_snapshot: list[dict[str, Any]] = []
        self._daemon_jobs_snapshot_at: datetime | None = None

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

    def _get_running_terminal_job(self) -> RunningTerminalJob | None:
        with self.lock:
            return self._running_terminal_job

    def has_running_terminal_job(self) -> bool:
        return self._get_running_terminal_job() is not None

    def has_interactive_terminal_context(self) -> bool:
        context = self._get_terminal_input_context()
        pending = self._get_pending_command()
        return bool(
            (context and context.input_mode == TERMINAL_INPUT_MODE_CONSOLE)
            or (pending and pending.input_mode == TERMINAL_INPUT_MODE_CONSOLE)
        )

    def mark_terminal_job_started(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> None:
        command = self._extract_command_text(tool_name, tool_args)
        timeout_seconds = _coerce_timeout_seconds(
            tool_args.get("timeout_seconds"),
            default=600,
        )
        reply_ticket_id = str(tool_args.get("_reply_ticket_id") or "").strip()
        source_type = ""
        source_label = ""
        if reply_ticket_id:
            try:
                from app.services.agent.reply_ticket import reply_ticket_manager

                ticket = reply_ticket_manager.get(reply_ticket_id)
                if ticket:
                    source_type = str(ticket.source_type or "")
                    source_label = str(ticket.source_label or "")
            except Exception:
                source_type = ""
                source_label = ""
        with self.lock:
            self._running_terminal_job = RunningTerminalJob(
                tool_name=tool_name,
                command=command,
                normalized_command=self._normalize_text(command),
                timeout_seconds=timeout_seconds,
                reply_ticket_id=reply_ticket_id,
                source_type=source_type,
                source_label=source_label,
            )

    def clear_terminal_job(self, command: str | None = None) -> None:
        normalized_command = self._normalize_text(command or "")
        with self.lock:
            running_job = self._running_terminal_job
            if not running_job:
                return
            if normalized_command and running_job.normalized_command != normalized_command:
                return
            self._running_terminal_job = None

    def _build_running_terminal_job_warning(
        self,
        running_job: RunningTerminalJob,
        command: str,
    ) -> str:
        elapsed_seconds = int((datetime.now() - running_job.started_at).total_seconds())
        return (
            f"\u540e\u53f0\u4efb\u52a1\u6b63\u5728\u8fd0\u884c\uff0c\u5df2\u8fd0\u884c {elapsed_seconds}s\u3002"
            "\u8fd9\u6761\u770b\u8d77\u6765\u662f\u4f1a\u5360\u7528\u524d\u53f0\u7ec8\u7aef\u7684 shell \u547d\u4ee4\uff0c"
            "\u5df2\u62e6\u622a\u672a\u53d1\u9001\u3002"
            "\u5982\u679c\u662f\u72ec\u7acb\u7684\u4e0b\u8f7d/\u5b89\u88c5/\u6784\u5efa\u4efb\u52a1\uff0c"
            "\u8bf7\u6539\u7528 mcp_local_run_job\uff1b\u4e0d\u540c\u540e\u53f0\u4efb\u52a1\u53ef\u4ee5\u5e76\u884c\u3002"
        )

    def _find_duplicate_background_job(self, command: str) -> dict[str, Any] | None:
        normalized_command = self._normalize_text(command or "")
        if not normalized_command:
            return None

        running_job = self._get_running_terminal_job()
        if running_job and running_job.normalized_command == normalized_command:
            return {
                "command": running_job.command,
                "elapsed_seconds": (
                    datetime.now() - running_job.started_at
                ).total_seconds(),
                "source": "session",
            }

        for job in self._get_daemon_jobs_snapshot():
            job_command = str(job.get("command") or "")
            if self._normalize_text(job_command) == normalized_command:
                return dict(job)

        return None

    def _build_duplicate_background_job_warning(
        self,
        duplicate_job: dict[str, Any],
    ) -> str:
        elapsed_raw = duplicate_job.get("elapsed_seconds") or 0
        try:
            elapsed_seconds = int(float(elapsed_raw))
        except (TypeError, ValueError):
            elapsed_seconds = 0
        job_id = str(duplicate_job.get("job_id") or "").strip()
        job_suffix = f" job_id={job_id}" if job_id else ""
        return (
            "\u540e\u53f0\u4efb\u52a1\u5df2\u5728\u8fd0\u884c"
            f"{job_suffix}\uff0c\u5df2\u8fd0\u884c {elapsed_seconds}s\u3002"
            "\u76f8\u540c\u547d\u4ee4\u5df2\u62e6\u622a\uff0c\u4e0d\u4f1a\u91cd\u590d\u53d1\u9001\u3002"
            "\u5982\u679c\u8981\u542f\u52a8\u53e6\u4e00\u4e2a\u4e0d\u540c\u7684\u540e\u53f0\u4efb\u52a1\uff0c"
            "\u8bf7\u53d1\u9001\u4e0d\u540c\u7684\u547d\u4ee4\u3002"
        )

    def _running_job_blocks_terminal_tool(
        self,
        *,
        running_job: RunningTerminalJob | None,
        tool_name: str,
        command: str,
    ) -> bool:
        if running_job is None:
            return False
        return (
            tool_name == EXECUTE_COMMAND_TOOL_NAME
            and classify_terminal_input_mode(command) == TERMINAL_INPUT_MODE_BUSY
        )

    def should_route_execute_command_to_background_job(self, command: str) -> bool:
        if self.has_interactive_terminal_context() or is_terminal_console_command(command):
            return False
        return should_route_command_to_background_job(command)

    def _should_auto_route_tool_to_job(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> bool:
        if self.has_interactive_terminal_context():
            return False
        if should_auto_route_terminal_tool_to_job(tool_name, tool_args):
            return True
        if tool_name != EXECUTE_COMMAND_TOOL_NAME:
            return False
        command = self._extract_command_text(tool_name, tool_args)
        return self.should_route_execute_command_to_background_job(command)

    def _validate_terminal_command_input(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> str | None:
        command = self._extract_command_text(tool_name, tool_args)

        if tool_name == RUN_JOB_TOOL_NAME:
            duplicate_job = self._find_duplicate_background_job(command)
            if duplicate_job:
                return self._build_duplicate_background_job_warning(duplicate_job)
            return None

        if (
            tool_name == EXECUTE_COMMAND_TOOL_NAME
            and self.has_interactive_terminal_context()
        ):
            with self.lock:
                active_context = self._terminal_input_context
                if active_context:
                    active_context.last_seen_at = datetime.now()
            return None

        running_job = self._get_running_terminal_job()
        if self._running_job_blocks_terminal_tool(
            running_job=running_job,
            tool_name=tool_name,
            command=command,
        ):
            return self._build_running_terminal_job_warning(running_job, command)

        if tool_name != EXECUTE_COMMAND_TOOL_NAME:
            return None

        pending = self._get_pending_command()
        if not pending:
            return None

        if pending.input_mode == TERMINAL_INPUT_MODE_BUSY:
            return (
                f"终端正在执行 `{self._short_command(pending.command)}`，前台进程通常不接收新的 shell 命令。"
                f"已拦截 `{self._short_command(command)}`，命令未发送；请等待当前任务结束，或明确要求中断。"
            )

        return None

    def validate_terminal_tool_input(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> str | None:
        return self._validate_terminal_command_input(tool_name, tool_args)

    def mark_terminal_command_dispatched(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> None:
        self._set_pending_command(tool_name, tool_args)
        self._emit_waiting_terminal_status(tool_name)

    def _set_pending_command(self, tool_name: str, tool_args: dict[str, Any]):
        command = self._extract_command_text(tool_name, tool_args)
        input_mode = classify_terminal_input_mode(command)
        if tool_name == EXECUTE_COMMAND_TOOL_NAME:
            context = self._get_terminal_input_context()
            current_pending = self._get_pending_command()
            if (
                context and context.input_mode == TERMINAL_INPUT_MODE_CONSOLE
            ) or (
                current_pending
                and current_pending.input_mode == TERMINAL_INPUT_MODE_CONSOLE
            ):
                input_mode = TERMINAL_INPUT_MODE_CONSOLE
        expected_output = _normalize_optional_text(tool_args.get("expected_output"))
        expected_regex = _normalize_optional_text(tool_args.get("expected_regex"))
        timeout_seconds = _coerce_timeout_seconds(
            tool_args.get("timeout_seconds"),
            PENDING_COMMAND_TIMEOUT_SECONDS,
        )
        auto_interrupt_on_timeout = _coerce_bool(
            tool_args.get("auto_interrupt_on_timeout"),
            False,
        )
        pending = PendingCommand(
            tool_name=tool_name,
            command=command,
            normalized_command=self._normalize_text(command),
            integration_contexts=self._capture_tool_integration_contexts(tool_args),
            log_line_cursor=self._get_log_line_count(),
            input_mode=input_mode,
            expected_output=expected_output,
            expected_regex=expected_regex,
            timeout_seconds=timeout_seconds,
            auto_interrupt_on_timeout=auto_interrupt_on_timeout,
            reply_ticket_id=str(tool_args.get("_reply_ticket_id") or "").strip(),
        )
        self._set_terminal_input_context(command, input_mode)
        terminal_command_state_manager.record(
            self.item_id,
            command,
            source="agent",
            expected_output=expected_output,
            expected_regex=expected_regex,
            timeout_seconds=timeout_seconds,
        )
        with self.lock:
            self._pending_command = pending
        self._update_pending_reply_waiting(pending)
        self._schedule_pending_command_recheck()

    @staticmethod
    def _parse_terminal_relay_command(command: str) -> tuple[str, str] | None:
        match = MINECRAFT_RELAY_COMMAND_RE.match(str(command or "").strip())
        if not match:
            return None
        player = str(match.group("player") or "").strip()
        question = str(match.group("question") or "").strip()
        if not player or not question:
            return None
        return player, question

    def _update_pending_reply_waiting(self, pending: PendingCommand) -> None:
        parsed = self._parse_terminal_relay_command(pending.command)
        if not parsed or not pending.reply_ticket_id:
            return
        target_player, question = parsed
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            reply_ticket_manager.upsert_pending_reply(
                pending.reply_ticket_id,
                status="waiting",
                awaiting_kind="minecraft_player",
                awaiting_key=target_player,
            )
            logger.info(
                "[AgentSession] Pending reply now awaits Minecraft player item=%s "
                "ticket=%s player=%s question=%s",
                self.item_id,
                pending.reply_ticket_id,
                target_player,
                question[:160],
            )
        except Exception as exc:
            logger.warning(
                "[AgentSession] Failed to update pending reply awaiting target: %s",
                exc,
            )

    def _clear_pending_command(self):
        self._cancel_pending_command_recheck()
        with self.lock:
            self._pending_command = None

    def _get_pending_command(self) -> PendingCommand | None:
        with self.lock:
            return self._pending_command

    def has_pending_command(self) -> bool:
        return self._get_pending_command() is not None

    def _capture_tool_integration_contexts(
        self,
        tool_args: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        context_token = str(tool_args.get("_robot_context_token") or "").strip()
        if not context_token:
            return {}

        try:
            from app.plugins.robot.mcp.context import get_robot_mcp_context

            context = get_robot_mcp_context(context_token)
            reply_target = getattr(context, "reply_target", None) if context else None
            robot_id = str(getattr(context, "robot_id", "") or "").strip()
            sender_key = str(getattr(context, "sender_key", "") or "").strip()
            if not robot_id or not sender_key or reply_target is None:
                return {}
            if hasattr(reply_target, "model_copy"):
                reply_target = reply_target.model_copy(deep=True)
            return {
                "robot": {
                    "robot_id": robot_id,
                    "sender_key": sender_key,
                    "reply_target": reply_target,
                    "conversation_key": str(
                        getattr(context, "conversation_key", "") or ""
                    ),
                    "conversation_generation": int(
                        getattr(context, "conversation_generation", 0) or 0
                    ),
                    # A terminal command result is a completion for an already accepted
                    # QQ request. It must be delivered even if the chat window slept
                    # before the shell produced output.
                    "reply_requires_awake": False,
                }
            }
        except Exception as exc:
            logger.warning(
                "[AgentSession] Failed to capture integration context for pending command item=%s: %s",
                self.item_id,
                exc,
            )
            return {}

    def _copy_pending_integration_contexts(
        self,
        pending: PendingCommand | None,
    ) -> dict[str, dict[str, Any]]:
        if not pending or not pending.integration_contexts:
            return {}
        contexts: dict[str, dict[str, Any]] = {}
        for name, context in pending.integration_contexts.items():
            copied = dict(context)
            reply_target = copied.get("reply_target")
            if hasattr(reply_target, "model_copy"):
                copied["reply_target"] = reply_target.model_copy(deep=True)
            contexts[name] = copied
        return contexts

    def _build_pending_source_context_prompt(
        self,
        pending: PendingCommand | None,
    ) -> str:
        contexts = self._copy_pending_integration_contexts(pending)
        if not pending or "robot" not in contexts:
            return ""
        robot_context = contexts["robot"]
        conversation_key = str(robot_context.get("conversation_key") or "").strip()
        sender_key = str(robot_context.get("sender_key") or "").strip()
        return (
            "Source routing for this terminal feedback:\n"
            "- The pending terminal command was started by a QQ robot conversation.\n"
            f"- Pending command: {pending.command}\n"
            f"- QQ conversation: {conversation_key or 'current locked conversation'}\n"
            f"- QQ sender_key: {sender_key or 'unknown'}\n"
            "- Use the terminal output only as evidence for that pending QQ request.\n"
            "- If you answer or update the user, call `mcp_robot_send_message` so the reply goes back to the locked QQ conversation. Do not leave the answer only in TermMan.\n"
            "- Treat this pending QQ request as one-shot: send at most one concise QQ status/final message for this command result. If you already sent a QQ message in this turn, do not restate the same conclusion in the final assistant text.\n"
        )

    def _get_reply_ticket(self, ticket_id: str):
        ticket_id = str(ticket_id or "").strip()
        if not ticket_id:
            return None
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            return reply_ticket_manager.get(ticket_id)
        except Exception:
            return None

    @staticmethod
    def _record_scheduled_ticket_result(
        ticket_id: str,
        *,
        success: bool,
        error: str = "",
    ) -> None:
        if not ticket_id:
            return
        try:
            from app.services.agent.scheduled_tasks import (
                record_scheduled_ticket_result,
            )

            record_scheduled_ticket_result(
                ticket_id,
                success=success,
                error=error,
            )
        except Exception:
            logger.exception(
                "[AgentSession] Failed to update scheduled task result: ticket=%s",
                ticket_id,
            )

    def _build_reply_ticket_prompt(self, ticket_id: str) -> str:
        ticket_id = str(ticket_id or "").strip()
        if not ticket_id:
            return ""
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            return reply_ticket_manager.build_prompt(ticket_id)
        except Exception:
            return ""

    def _deliver_terminal_reply_ticket(
        self,
        ticket_id: str,
        content: str,
    ) -> bool:
        ticket = self._get_reply_ticket(ticket_id)
        if not ticket or not content.strip():
            return False
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            if ticket.source_type == "qq":
                delivered = reply_ticket_manager.deliver(ticket_id, content)
                if delivered:
                    self.emit_output(
                        f"已回复 QQ：{content.strip()}",
                        ROBOT_QQ_REPLY_EVENT_TYPE,
                        {"tool_name": "reply_ticket", "qq_delivery": True},
                    )
                return delivered
        except Exception:
            logger.exception(
                "[AgentSession] Failed to deliver terminal reply ticket: item=%s ticket=%s",
                self.item_id,
                ticket_id,
            )
        return False

    def _fail_and_report_pending_reply(
        self,
        ticket_id: str,
        *,
        report: str,
        reason: str,
    ) -> bool:
        ticket = self._get_reply_ticket(ticket_id)
        if not ticket or not ticket.pending_reply_active:
            return False
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            task_workflow_manager.update(
                ticket_id,
                action="mark_blocked",
                note=str(reason or report)[:2000],
            )
            reply_ticket_manager.mark_failed(ticket_id, reason or report)
            delivered, detail = reply_ticket_manager.send_pending_reply(
                ticket_id,
                report,
            )
            if delivered and ticket.source_type == "qq":
                self.emit_output(
                    f"已回复 QQ：{report.strip()}",
                    ROBOT_QQ_REPLY_EVENT_TYPE,
                    {"tool_name": "reply_ticket", "qq_delivery": True},
                )
            elif not delivered:
                self.emit_output(
                    f"任务失败汇报尚未送达，任务已保留：{detail}",
                    "agent_warning",
                )
            return delivered
        except Exception:
            logger.exception(
                "[AgentSession] Failed to report pending task failure: item=%s ticket=%s",
                self.item_id,
                ticket_id,
            )
            return False

    def _attach_reply_ticket_to_agent(self, agent: Agent, ticket_id: str) -> None:
        ticket_id = str(ticket_id or "").strip()
        if not ticket_id:
            return
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            reply_ticket_manager.attach_to_agent(agent, ticket_id)
        except Exception:
            context = getattr(agent, "_context", None)
            if context is not None:
                context.reply_ticket_id = ticket_id

    def _detach_reply_ticket_from_agent(self, agent: Agent, ticket_id: str) -> None:
        ticket_id = str(ticket_id or "").strip()
        if not ticket_id:
            return
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            reply_ticket_manager.detach_from_agent(agent, ticket_id)
        except Exception:
            context = getattr(agent, "_context", None)
            if (
                context is not None
                and str(getattr(context, "reply_ticket_id", "") or "") == ticket_id
            ):
                context.reply_ticket_id = ""

    def _robot_send_blocked_by_reply_ticket(self, ticket_id: str, tool_name: str) -> str:
        if tool_name != ROBOT_SEND_TOOL_NAME:
            return ""
        ticket = self._get_reply_ticket(ticket_id)
        if not ticket:
            return ""
        if ticket.source_type == "qq":
            return ""
        return (
            "\u5df2\u62e6\u622a QQ \u53d1\u9001\uff1a"
            "\u5f53\u524d\u540e\u53f0\u4efb\u52a1\u7684\u53d1\u8d77\u6765\u6e90"
            f"\u662f {ticket.source_label or ticket.source_type}\uff0c"
            "\u53ea\u80fd\u56de\u5230\u539f\u59cb\u6765\u6e90\uff0c\u4e0d\u80fd\u8f6c\u53d1\u5230 QQ\u3002"
        )

    def _send_pending_integration_response(
        self,
        pending: PendingCommand | None,
        content: str,
        *,
        message_sent: bool = False,
    ) -> bool:
        contexts = self._copy_pending_integration_contexts(pending)
        if not contexts or not content.strip():
            return False
        if pending and pending.integration_response_sent:
            return False
        if pending and message_sent:
            self._mark_pending_integration_response_sent(pending)
            return True
        try:
            delivered = send_integration_final_response_fallback(
                contexts,
                content=content,
                message_sent=message_sent,
            )
            if delivered and pending:
                self._mark_pending_integration_response_sent(pending)
            return delivered
        except Exception as exc:
            logger.warning(
                "[AgentSession] Failed to send pending integration response item=%s: %s",
                self.item_id,
                exc,
            )
            return False

    def _mark_pending_integration_response_sent(self, pending: PendingCommand) -> None:
        pending.integration_response_sent = True
        with self.lock:
            current_pending = self._pending_command
            if (
                current_pending
                and current_pending.normalized_command == pending.normalized_command
            ):
                current_pending.integration_response_sent = True

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
            f"{pending.timeout_seconds} 秒内没有读取到新的原生日志反馈。"
        )

    def _pending_expectation_matches(
        self,
        pending: PendingCommand,
        content: str,
    ) -> bool:
        if not content:
            return False
        if pending.expected_output and pending.expected_output in content:
            return True
        if not pending.expected_regex:
            return False
        try:
            return re.search(pending.expected_regex, content, re.MULTILINE) is not None
        except re.error as exc:
            logger.warning(
                "[AgentSession] Invalid pending command expected_regex for item=%s, command=%s, regex=%s, error=%s",
                self.item_id,
                pending.command,
                pending.expected_regex,
                exc,
            )
            return False

    def _send_interrupt_for_pending_timeout(self, pending: PendingCommand) -> bool:
        try:
            from app.services.socket_pool import InputSDK

            success = InputSDK().send(self.item_id, "\x03")
            logger.info(
                "[AgentSession] Auto interrupt sent for timed-out expected command item=%s, command=%s, success=%s",
                self.item_id,
                pending.command,
                success,
            )
            return bool(success)
        except Exception as exc:
            logger.warning(
                "[AgentSession] Failed to auto interrupt timed-out expected command item=%s, command=%s, error=%s",
                self.item_id,
                pending.command,
                exc,
            )
            return False

    def _build_expected_command_timeout_feedback(
        self,
        pending: PendingCommand,
        interrupted: bool,
    ) -> str:
        if pending.auto_interrupt_on_timeout:
            interrupt_text = (
                "已按显式配置发送 Ctrl+C。"
                if interrupted
                else "按显式配置尝试发送 Ctrl+C，但发送失败。"
            )
        else:
            interrupt_text = "未中断当前进程，请结合上一条命令和最新终端输出排查。"
        return (
            f"命令 `{pending.command}` 在 {pending.timeout_seconds} 秒内没有匹配预期输出 "
            f"`{pending.expectation_label()}`。{interrupt_text}"
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

        if pending.has_expectation() and elapsed_seconds >= pending.timeout_seconds:
            recent_feedback = self._get_recent_pending_log_tail(64)
            if not self._pending_expectation_matches(pending, recent_feedback):
                logger.warning(
                    "[AgentSession] Pending command timed out without expected output for item=%s, command=%s, expected=%s",
                    self.item_id,
                    pending.command,
                    pending.expectation_label(),
                )
                self._clear_pending_command()
                interrupted = False
                if pending.auto_interrupt_on_timeout:
                    interrupted = self._send_interrupt_for_pending_timeout(pending)
                timeout_message = self._build_expected_command_timeout_feedback(
                    pending,
                    interrupted,
                )
                self._send_pending_integration_response(pending, timeout_message)
                self.emit_output(
                    timeout_message,
                    "agent_warning",
                    {"tool_name": pending.tool_name},
                )
                return

        if not has_new_log_lines and not should_force_tail_check:
            if elapsed_seconds >= pending.timeout_seconds:
                logger.warning(
                    "[AgentSession] Pending command timed out without raw feedback for item=%s, command=%s",
                    self.item_id,
                    pending.command,
                )
                self._clear_pending_command()
                timeout_message = self._build_missing_command_feedback(pending)
                self._send_pending_integration_response(pending, timeout_message)
                self.emit_output(
                    timeout_message,
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

    def discard_pending_terminal_feedback_delta(self) -> None:
        pending = self._get_pending_command()
        if not pending:
            return
        try:
            new_cursor = self._get_log_line_count()
        except Exception as exc:
            logger.debug(
                "[AgentSession] Failed to advance pending log cursor for item=%s: %s",
                self.item_id,
                exc,
            )
            return
        with self.lock:
            current_pending = self._pending_command
            if current_pending and current_pending.normalized_command == pending.normalized_command:
                current_pending.log_line_cursor = max(
                    current_pending.log_line_cursor,
                    new_cursor,
                )
        self._emit_waiting_terminal_status(pending.tool_name)
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
        if pending.has_expectation():
            if self._pending_expectation_matches(pending, content):
                logger.info(
                    "[AgentSession] Pending command matched expected output for item=%s, command=%s, expected=%s",
                    self.item_id,
                    pending.command,
                    pending.expectation_label(),
                )
                self._clear_pending_command()
                return False, None, False
            logger.info(
                "[AgentSession] Holding pending command until expected output appears for item=%s, command=%s, expected=%s",
                self.item_id,
                pending.command,
                pending.expectation_label(),
            )
            self._emit_waiting_terminal_status(pending.tool_name)
            return True, None, False
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
                logger.info(
                    "[AgentSession] Holding busy command feedback until prompt returns for item=%s, command=%s",
                    self.item_id,
                    pending.command,
                )
                self._emit_waiting_terminal_status(pending.tool_name)
                return True, None, False
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
                    > current_pending.timeout_seconds
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

    def _should_display_pending_held_output(
        self,
        content: str,
        pending: PendingCommand | None,
    ) -> bool:
        if not pending:
            return False
        lines = [line for line in content.splitlines() if line.strip()]
        informative_lines = [line for line in lines if not self._is_prompt_only_line(line)]
        return bool(informative_lines) and all(
            self._is_command_echo_line(line, pending) for line in informative_lines
        )

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
        if str(last_item.reply_ticket_id or "") != str(input_msg.reply_ticket_id or ""):
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

    def process_queue(self):
        while True:
            try:
                input_msg = self.input_queue.get(timeout=1)
            except queue.Empty:
                with self.lock:
                    self.state = SessionState.IDLE
                self._emit_idle_or_waiting_status(0)
                return

            if (
                input_msg.input_type != InputType.SCHEDULED_TASK
                and not input_msg.reply_ticket_id
                and (datetime.now() - input_msg.timestamp).total_seconds() > 60
            ):
                logger.debug(f"[AgentSession] Skipping stale input for item {self.item_id}")
                continue

            self._begin_turn(input_msg)

            process_error = ""
            try:
                self._process_input(input_msg)
            except Exception as exc:
                process_error = str(exc)
                logger.error(f"[AgentSession] Error processing queue: {exc}")
                self.emit_output(f"处理失败: {exc}", "agent_error")
            finally:
                self._finish_turn()
                self._notify_input_complete(input_msg, not process_error, process_error)

    def process_input(self, input_msg: InputMessage):
        with self.lock:
            if self.state in {SessionState.RUNNING, SessionState.INTERRUPTING}:
                self.queue_input(input_msg)
                return

        self._begin_turn(input_msg)

        process_error = ""
        try:
            self._process_input(input_msg)
        except Exception as exc:
            process_error = str(exc)
            raise
        finally:
            self._finish_turn()
            self._notify_input_complete(input_msg, not process_error, process_error)

            if not self.input_queue.empty():
                threading.Thread(target=self.process_queue, daemon=True).start()

    @staticmethod
    def _notify_input_complete(
        input_msg: InputMessage,
        processed: bool,
        process_error: str = "",
    ) -> None:
        callback = input_msg.completion_callback
        if callback is None:
            return
        try:
            callback(processed, process_error)
        except Exception:
            logger.exception("[AgentSession] Input completion callback failed")

    def _process_input(self, input_msg: InputMessage):
        with agent_turn_coordinator.turn(agent_turn_key(self.handler_id)):
            self._process_input_serialized(input_msg)

    def _process_input_serialized(self, input_msg: InputMessage):
        if input_msg.callback:
            self.add_output_callback(input_msg.callback)
        agent = self.get_agent()
        if not agent:
            self.emit_output("Agent 不可用", "agent_error")
            return

        self._last_activity = datetime.now()

        if input_msg.input_type == InputType.TERMINAL:
            self._attach_reply_ticket_to_agent(agent, input_msg.reply_ticket_id)
            try:
                self._process_terminal_input(input_msg, agent)
            finally:
                self._detach_reply_ticket_from_agent(agent, input_msg.reply_ticket_id)
        elif input_msg.input_type == InputType.SCHEDULED_TASK:
            from app.services.agent.reply_ticket import reply_ticket_manager

            if not input_msg.reply_ticket_id:
                ticket = reply_ticket_manager.create_for_scheduled_task(
                    agent,
                    item_id=self.item_id,
                    handler_id=self.handler_id,
                    message=input_msg.content,
                    scheduled_task_id=input_msg.scheduled_task_id,
                    scheduled_execution_id=input_msg.scheduled_execution_id,
                )
                input_msg.reply_ticket_id = ticket.ticket_id
            else:
                self._attach_reply_ticket_to_agent(agent, input_msg.reply_ticket_id)
            try:
                self._process_chat_input(input_msg, agent)
            finally:
                self._detach_reply_ticket_from_agent(agent, input_msg.reply_ticket_id)
        else:
            self._process_chat_input(input_msg, agent)

    def _process_terminal_input(self, input_msg: InputMessage, agent: Agent):
        combined_input = "\n".join(
            part
            for part in (input_msg.content, input_msg.raw_content)
            if part and part.strip()
        )
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            matched_entry = reply_ticket_manager.match_pending_reply(
                self.item_id,
                combined_input,
            )
            if matched_entry:
                input_msg.reply_ticket_id = str(matched_entry["id"])
                self._attach_reply_ticket_to_agent(agent, input_msg.reply_ticket_id)
            elif not input_msg.reply_ticket_id and self._get_pending_command() is None:
                player_chat = MINECRAFT_PLAYER_CHAT_CAPTURE_RE.search(combined_input)
                if player_chat:
                    player = str(player_chat.group("player") or "").strip()
                    message = str(player_chat.group("message") or "").strip()
                    ticket = reply_ticket_manager.create_for_terminal(
                        agent,
                        item_id=self.item_id,
                        handler_id=self.handler_id,
                        player=player,
                        message=message,
                    )
                    input_msg.reply_ticket_id = ticket.ticket_id
        except Exception:
            logger.exception(
                "[AgentSession] Failed to resolve terminal pending-reply source: item=%s",
                self.item_id,
            )

        reply_ticket = self._get_reply_ticket(input_msg.reply_ticket_id)
        reply_ticket_is_web = bool(
            reply_ticket and getattr(reply_ticket, "source_type", "") == "web"
        )
        pending_before_analysis = self._get_pending_command()
        had_pending_command = pending_before_analysis is not None
        pending_integration_contexts = self._copy_pending_integration_contexts(
            pending_before_analysis
        )
        if reply_ticket_is_web or not pending_integration_contexts:
            clear_robot_context = getattr(agent, "clear_robot_context", None)
            if callable(clear_robot_context):
                clear_robot_context()
        analysis = self._resolve_terminal_analysis_content(input_msg)
        if input_msg.content:
            attach_terminal_feedback_to_pending_continuation(self.item_id, input_msg.content)
        should_emit_terminal_output = bool(input_msg.content) and (
            not had_pending_command
            or bool(analysis.content)
            or self._should_display_pending_held_output(
                input_msg.content,
                pending_before_analysis,
            )
        )
        if should_emit_terminal_output:
            self.emit_output(input_msg.content, "terminal_output")
        if not analysis.content:
            return
        if analysis.direct_response:
            integration_already_sent = bool(
                pending_before_analysis
                and pending_before_analysis.integration_response_sent
            )
            integration_delivered = self._send_pending_integration_response(
                pending_before_analysis,
                analysis.content,
            )
            if not (integration_already_sent or integration_delivered):
                self.emit_output(analysis.content, "agent_response")
            self._record_scheduled_ticket_result(
                input_msg.reply_ticket_id,
                success=True,
            )
            return

        transient_integration_tools_added = False
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            if pending_integration_contexts:
                setup_integration_chat_contexts(agent, pending_integration_contexts)
            loop.run_until_complete(agent.start_mcp_servers())
            if pending_integration_contexts:
                loop.run_until_complete(
                    ensure_integration_chat_context_tools(
                        agent,
                        pending_integration_contexts,
                    )
                )
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
                pending_command=pending_before_analysis,
            )
            extract_integration_context_targets(agent, messages)
            tools = select_tools_for_turn(
                agent.get_tools_for_litellm(),
                source="terminal",
                query=input_msg.query or analysis.content,
                agent=agent,
                reply_ticket_id=input_msg.reply_ticket_id,
            )
            turn_guard = TurnGuard()
            self._current_turn_id = turn_guard.turn_id
            self._emit_running_terminal_status(analysis.terminal_source)
            terminal_delivery_retry_used = False
            pending_reply_delivery_retry_used = False
            integration_tool_results: list[str] = []
            terminal_failure_report = ""

            for _ in range(MAX_ITERATIONS):
                timed_out, timeout_reason = turn_guard.check_timeout()
                if timed_out:
                    terminal_failure_report = "任务未能完成：本轮处理超时，已停止该任务。"
                    self._send_pending_integration_response(
                        pending_before_analysis,
                        timeout_reason,
                    )
                    self.emit_output(timeout_reason, "agent_warning")
                    break

                if self._abort_flag:
                    terminal_failure_report = "任务已被中断，未能完成。"
                    self.emit_output("当前轮已中断", "agent_warning")
                    self.emit_status("interrupted", "当前轮已中断")
                    break

                response = self._call_llm(agent, messages, tools=tools)
                message = self._normalize_dsml_tool_message(
                    response.choices[0].message,
                    tools,
                )

                if not (hasattr(message, "tool_calls") and message.tool_calls):
                    if message.content:
                        final_content = guard_ungrounded_tool_claim(
                            message.content,
                            tool_called=turn_guard.tool_call_count > 0,
                        )
                        can_finalize, workflow_correction = (
                            task_workflow_manager.can_finalize(
                                input_msg.reply_ticket_id
                            )
                        )
                        if not can_finalize:
                            messages.append(
                                {"role": "assistant", "content": final_content}
                            )
                            messages.append(
                                {"role": "system", "content": workflow_correction}
                            )
                            self._emit_running_terminal_status(
                                analysis.terminal_source
                            )
                            continue
                        reply_ticket = self._get_reply_ticket(
                            input_msg.reply_ticket_id
                        )
                        if reply_ticket and reply_ticket.pending_reply_active:
                            if not pending_reply_delivery_retry_used:
                                messages.append(
                                    {"role": "assistant", "content": final_content}
                                )
                                messages.append(
                                    {
                                        "role": "system",
                                        "content": (
                                            "The task belongs to an active pending-reply queue entry. "
                                            "Do not return normal final text. Call "
                                            "mcp_local_write_pending_reply(status=ready) if needed, "
                                            "then call mcp_local_send_pending_reply with entry_id="
                                            f"{reply_ticket.ticket_id} and the concise final report."
                                        ),
                                    }
                                )
                                pending_reply_delivery_retry_used = True
                                continue
                            self.emit_output(
                                "待回复任务尚未通过发送工具汇报，队列记录已保留。",
                                "agent_warning",
                            )
                            terminal_failure_report = (
                                "任务未能完成：Agent 未能生成有效的最终汇报，已停止该任务。"
                            )
                            break
                        if should_retry_terminal_source_delivery(
                            agent=agent,
                            terminal_content=analysis.content,
                            terminal_source=analysis.terminal_source,
                            final_response=final_content,
                            retry_used=terminal_delivery_retry_used,
                        ):
                            messages.append({"role": "assistant", "content": final_content})
                            messages.append(
                                build_terminal_source_delivery_correction_message(final_content)
                            )
                            terminal_delivery_retry_used = True
                            self._emit_running_terminal_status(analysis.terminal_source)
                            continue
                        if pending_integration_contexts:
                            message_sent = (
                                integration_message_sent(integration_tool_results)
                            )
                            integration_delivered = self._send_pending_integration_response(
                                pending_before_analysis,
                                final_content,
                                message_sent=message_sent,
                            )
                            if message_sent or integration_delivered:
                                break
                        reply_ticket = self._get_reply_ticket(
                            input_msg.reply_ticket_id
                        )
                        if (
                            reply_ticket
                            and reply_ticket.source_type == "qq"
                            and self._deliver_terminal_reply_ticket(
                                input_msg.reply_ticket_id,
                                final_content,
                            )
                        ):
                            break
                        self.emit_output(final_content, "agent_response")
                        if reply_ticket and reply_ticket.source_type == "web":
                            try:
                                from app.services.agent.reply_ticket import (
                                    reply_ticket_manager,
                                )

                                reply_ticket_manager.mark_delivered(
                                    input_msg.reply_ticket_id
                                )
                            except Exception:
                                logger.exception(
                                    "[AgentSession] Failed to complete web reply ticket: item=%s ticket=%s",
                                    self.item_id,
                                    input_msg.reply_ticket_id,
                                )
                        self._record_scheduled_ticket_result(
                            input_msg.reply_ticket_id,
                            success=True,
                        )
                    break

                next_messages = self._handle_tool_calls(
                    agent,
                    loop,
                    messages,
                    message,
                    turn_guard,
                    terminal_source=analysis.terminal_source,
                    tool_results_sink=integration_tool_results,
                    pending_command_for_delivery=pending_before_analysis,
                    reply_ticket_id=input_msg.reply_ticket_id,
                )
                if next_messages is None:
                    break
                messages = next_messages
            else:
                terminal_failure_report = (
                    "任务未能完成：Agent 达到本轮处理次数上限，已停止该任务。"
                )

            if terminal_failure_report:
                self._fail_and_report_pending_reply(
                    input_msg.reply_ticket_id,
                    report=terminal_failure_report,
                    reason=terminal_failure_report,
                )

            if pending_integration_contexts:
                clear_integration_chat_contexts(agent, pending_integration_contexts)
            if transient_integration_tools_added:
                clear_terminal_alert_integration_tools(agent)
            loop.close()
        except Exception as exc:
            logger.error(f"[AgentSession] Terminal processing error: {exc}")
            self.emit_output(f"处理失败: {exc}", "agent_error")
            self._fail_and_report_pending_reply(
                input_msg.reply_ticket_id,
                report=f"任务处理失败：{exc}",
                reason=str(exc),
            )
            self._record_scheduled_ticket_result(
                input_msg.reply_ticket_id,
                success=False,
                error=str(exc),
            )

            if transient_integration_tools_added:
                clear_terminal_alert_integration_tools(agent)
            if pending_integration_contexts:
                clear_integration_chat_contexts(agent, pending_integration_contexts)
            if loop is not None and not loop.is_closed():
                loop.close()

    def _process_chat_input(self, input_msg: InputMessage, agent: Agent):
        if input_msg.callback:
            self.add_output_callback(input_msg.callback)

        try:
            clear_robot_context = getattr(agent, "clear_robot_context", None)
            if callable(clear_robot_context):
                clear_robot_context()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(agent.start_mcp_servers())

            messages = self._build_chat_messages(agent, input_msg)
            tools = select_tools_for_turn(
                agent.get_tools_for_litellm(),
                source="web",
                query=input_msg.query or input_msg.content,
                agent=agent,
                reply_ticket_id=input_msg.reply_ticket_id,
            )
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

                response = self._call_llm(agent, messages, tools=tools)
                message = self._normalize_dsml_tool_message(
                    response.choices[0].message,
                    tools,
                )

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
        pending_command: PendingCommand | None = None,
    ) -> list[dict]:
        effective_terminal_content = terminal_content or input_msg.content
        pending_command = pending_command or self._get_pending_command()
        messages = build_terminal_turn_messages(
            agent,
            item_id=self.item_id,
            terminal_content=effective_terminal_content,
            query=(input_msg.query or effective_terminal_content or "")[:500],
            terminal_source=terminal_source,
            pending_command=pending_command.command if pending_command else "",
            pending_source_context=self._build_pending_source_context_prompt(
                pending_command
            ),
        )
        last_command_context = terminal_command_state_manager.build_prompt_context(
            self.item_id
        )
        if last_command_context:
            insert_at = max(len(messages) - 1, 0)
            messages.insert(
                insert_at,
                {"role": "system", "content": last_command_context},
            )
        terminal_text = (effective_terminal_content or "").strip()
        if terminal_text:
            has_system_prompt = any(
                message.get("role") == "system" for message in messages
            )
            if not has_system_prompt:
                system_parts = [get_system_prompt(agent)]
                try:
                    for skill in agent.match_skills(
                        (input_msg.query or effective_terminal_content or "")[:500]
                    ):
                        action = getattr(skill, "action", None)
                        prompt = str(getattr(action, "prompt", "") or "").strip()
                        if prompt:
                            system_parts.append(prompt)
                except Exception:
                    pass
                messages = [
                    {"role": "system", "content": "\n\n".join(system_parts)}
                ] + messages

            reply_ticket_prompt = self._build_reply_ticket_prompt(
                input_msg.reply_ticket_id
            )
            if reply_ticket_prompt:
                insert_at = 1 if messages and messages[0].get("role") == "system" else 0
                messages.insert(
                    insert_at,
                    {"role": "system", "content": reply_ticket_prompt},
                )

            last_user_content = ""
            if messages and messages[-1].get("role") == "user":
                last_user_content = str(messages[-1].get("content") or "")
            if terminal_text not in last_user_content:
                source_label = prompt_builder.FILTERED_TERMINAL_LABEL
                if terminal_source == TERMINAL_SOURCE_RAW_FEEDBACK:
                    source_label = prompt_builder.RAW_TERMINAL_LABEL
                messages.append(
                    {
                        "role": "user",
                        "content": f"{source_label}:\n{terminal_text}",
                    }
                )
        self.inject_active_jobs_prompt_context(messages)
        return messages

    def _build_running_terminal_job_prompt_context(
        self,
        running_job: RunningTerminalJob,
    ) -> str:
        elapsed_seconds = int((datetime.now() - running_job.started_at).total_seconds())
        source_line = ""
        if running_job.source_type or running_job.source_label:
            source_line = (
                "Original requester route: "
                f"{running_job.source_label or running_job.source_type}. "
                "When this job completes, report back only through that same route. "
                "Do not switch to QQ unless this route is QQ. "
            )
        return (
            "A background terminal job is running independently; it does not block normal conversation. "
            "For normal chat, acknowledgement, or 'why are you quiet' messages, answer directly without calling run_job. "
            "Only inspect/list/cancel jobs when the user explicitly asks about the job status or wants to stop it. "
            f"{source_line}"
            "当前有一个后台终端任务正在运行。"
            f"已运行 {elapsed_seconds}s，超时上限 {running_job.timeout_seconds}s。"
            f"任务命令：`{self._short_command(running_job.command)}`。"
            "你可以正常回答不需要终端的新问题。"
            "如果用户问任务状态，只说明后台任务仍在运行，完成后系统会把最终结果作为新的终端反馈发给你。"
            "不同的后台任务可以继续用 run_job 启动；不要重复启动完全相同的命令。"
            "如果涉及 apt/dpkg 等有全局锁的安装任务，优先等当前同类安装完成，或先 list_jobs 确认。"
            "但如果当前终端是已启动的交互式控制台，可以继续用 execute_command 发送安全的控制台输入，"
            "例如 Minecraft 的 say/tell/op/give/setblock/fill/summon 等单条控制台命令。"
            "如果确实要终止任务，先 list_jobs 再 cancel_job。"
        )

    def _get_daemon_jobs_snapshot(self) -> list[dict[str, Any]]:
        now = datetime.now()
        with self.lock:
            snapshot_at = self._daemon_jobs_snapshot_at
            if (
                snapshot_at is not None
                and (now - snapshot_at).total_seconds()
                < DAEMON_JOBS_CONTEXT_REFRESH_SECONDS
            ):
                return [dict(job) for job in self._daemon_jobs_snapshot]

        jobs: list[dict[str, Any]] = []
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item
            from app.services import DaemonConfig, connection_manager

            try:
                item_uuid = uuid.UUID(str(self.item_id))
            except ValueError:
                return []

            with Session(engine) as db:
                item = db.get(Item, item_uuid)
                if (
                    item is None
                    or not item.socket_host
                    or not item.socket_port
                    or not item.api_key
                ):
                    return []
                daemon_config = DaemonConfig(
                    item.socket_host,
                    item.socket_port,
                    item.api_key,
                )

            connection = connection_manager.get_or_create_connection(daemon_config)
            result = connection.list_jobs_http(item_uuid=str(self.item_id))
            raw_jobs = result.get("jobs") if result.get("success") else []
            if isinstance(raw_jobs, list):
                jobs = [dict(job) for job in raw_jobs if isinstance(job, dict)]
        except Exception as exc:
            logger.debug(
                "[AgentSession] Failed to fetch daemon jobs snapshot for item=%s: %s",
                self.item_id,
                exc,
            )
            jobs = []

        with self.lock:
            self._daemon_jobs_snapshot = [dict(job) for job in jobs]
            self._daemon_jobs_snapshot_at = now
        return jobs

    def _build_daemon_jobs_prompt_context(self, jobs: list[dict[str, Any]]) -> str:
        if not jobs:
            return ""

        lines = [
            "Active daemon background jobs snapshot:",
            "These jobs are still running in daemon. This snapshot is included every turn so the agent does not lose track of background work.",
        ]
        for index, job in enumerate(jobs[:5], start=1):
            command = self._short_command(str(job.get("command") or ""), max_length=160)
            elapsed_raw = job.get("elapsed_seconds") or 0
            try:
                elapsed_seconds = int(float(elapsed_raw))
            except (TypeError, ValueError):
                elapsed_seconds = 0
            lines.append(
                f"- {index}. job_id={job.get('job_id', '')} "
                f"elapsed={elapsed_seconds}s "
                f"cancel_requested={bool(job.get('cancel_requested'))} "
                f"command={command}"
            )
            output_tail = str(job.get("output_tail") or "").strip()
            if output_tail:
                if len(output_tail) > 1200:
                    output_tail = output_tail[-1200:]
                lines.append(f"  output_tail:\n{output_tail}")
        lines.append(
            "Rules: do not assume a listed job has completed; different background jobs may run in parallel when the user explicitly asks for separate work; do not start an exact duplicate of an already listed command; for apt/dpkg/package-manager installs that may share global locks, prefer waiting for the current same-manager install to finish or inspect with `mcp_local_list_jobs`; if the user asks status, answer from this snapshot or call `mcp_local_list_jobs`; if they ask to stop it, call `mcp_local_cancel_job` with the job_id."
        )
        return "\n".join(lines)

    def build_active_jobs_prompt_context(self) -> str:
        parts: list[str] = []
        running_job = self._get_running_terminal_job()
        if running_job:
            parts.append(self._build_running_terminal_job_prompt_context(running_job))

        daemon_jobs_context = self._build_daemon_jobs_prompt_context(
            self._get_daemon_jobs_snapshot()
        )
        if daemon_jobs_context:
            parts.append(daemon_jobs_context)

        return "\n\n".join(parts)

    def inject_active_jobs_prompt_context(self, messages: list[dict]) -> None:
        context = self.build_active_jobs_prompt_context()
        if not context:
            return
        messages.insert(
            max(len(messages) - 1, 0),
            {
                "role": "system",
                "content": context,
            },
        )

    def _build_chat_messages(self, agent: Agent, input_msg: InputMessage) -> list[dict]:
        pending_context = build_pending_terminal_continuation_prompt(
            self.item_id,
            input_msg.content,
        )
        messages = build_chat_turn_messages(
            agent,
            item_id=self.item_id,
            message=input_msg.content,
            query=input_msg.query or input_msg.content,
            pending_context=pending_context,
        )
        self.inject_active_jobs_prompt_context(messages)
        return messages

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

    def _call_llm(
        self,
        agent: Agent,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
    ):
        effective_tools = agent.get_tools_for_litellm() if tools is None else tools
        kwargs = build_litellm_completion_kwargs(
            model=agent._context.model,
            messages=messages,
            timeout=REQUEST_TIMEOUT,
            tools=effective_tools,
            api_key=agent._context.api_key,
            api_base=agent._context.api_url,
            model_parameters=getattr(agent._context, "model_parameters", {}),
        )

        return completion(**kwargs)

    @staticmethod
    def _normalize_dsml_tool_message(message: Any, tools: list[dict]) -> Any:
        raw_content = str(getattr(message, "content", "") or "")
        allowed_tool_names = {
            str(tool.get("function", {}).get("name") or "").strip()
            for tool in tools
            if str(tool.get("function", {}).get("name") or "").strip()
        }
        visible_content, dsml_calls = extract_dsml_tool_calls(
            raw_content,
            allowed_tool_names=allowed_tool_names,
        )
        native_tool_calls = list(getattr(message, "tool_calls", None) or [])
        if native_tool_calls:
            return SimpleNamespace(
                content=visible_content,
                tool_calls=native_tool_calls,
            )
        if not dsml_calls and visible_content == raw_content:
            return message
        return SimpleNamespace(
            content=visible_content,
            tool_calls=[
                SimpleNamespace(
                    id=tool_call["id"],
                    type=tool_call["type"],
                    function=SimpleNamespace(**tool_call["function"]),
                )
                for tool_call in dsml_calls
            ],
        )

    def _handle_tool_calls(
        self,
        agent: Agent,
        loop: asyncio.AbstractEventLoop,
        messages: list[dict],
        message: Any,
        turn_guard: TurnGuard,
        terminal_source: str | None = None,
        tool_results_sink: list[str] | None = None,
        pending_command_for_delivery: PendingCommand | None = None,
        reply_ticket_id: str = "",
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
            robot_send_source_error = self._robot_send_blocked_by_reply_ticket(
                reply_ticket_id,
                tool_name,
            )
            if robot_send_source_error:
                logger.info(
                    "[AgentSession] Blocked robot send for non-QQ reply ticket: item=%s tool=%s reason=%s",
                    self.item_id,
                    tool_name,
                    robot_send_source_error,
                )
                return None
            tool_args["item_id"] = self.item_id
            if reply_ticket_id:
                tool_args["_reply_ticket_id"] = reply_ticket_id
            terminal_input_error = None
            if not self._should_auto_route_tool_to_job(tool_name, tool_args):
                terminal_input_error = self._validate_terminal_command_input(tool_name, tool_args)
            if terminal_input_error:
                self._send_pending_integration_response(
                    pending_command_for_delivery,
                    terminal_input_error,
                )
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

            if tool_name != "mcp_local_update_task_workflow":
                task_workflow_manager.record_tool_call(
                    reply_ticket_id,
                    tool_name=tool_name,
                    command=str(tool_args.get("command") or ""),
                )

            result = loop.run_until_complete(agent.execute_tool(tool_name, tool_args))
            logger.info(f"[AgentSession] Tool {tool_name} executed")
            if tool_name == RUN_JOB_TOOL_NAME:
                turn_guard.reset_timeout_window()

            result_text = self._format_tool_result(result).strip()
            pending_reply_sent = is_pending_reply_sent_result(result)
            robot_delivery_result = bool(
                tool_name == ROBOT_SEND_TOOL_NAME
                and result_text
                and integration_message_sent([result_text])
            )
            delivery_is_final = True
            if robot_delivery_result:
                delivery_is_final, _ = task_workflow_manager.can_finalize(
                    reply_ticket_id
                )
            if (
                tool_results_sink is not None
                and result_text
                and not (robot_delivery_result and not delivery_is_final)
            ):
                tool_results_sink.append(result_text)
            if robot_delivery_result:
                if delivery_is_final:
                    try:
                        from app.services.agent.reply_ticket import (
                            reply_ticket_manager,
                        )

                        reply_ticket_manager.mark_delivered(reply_ticket_id)
                    except Exception:
                        logger.exception(
                            "[AgentSession] Failed to mark QQ reply delivered: item=%s ticket=%s",
                            self.item_id,
                            reply_ticket_id,
                        )
                else:
                    task_workflow_manager.update(
                        reply_ticket_id,
                        action="record_progress",
                        note="Sent an intermediate status update; the main task remains active.",
                    )
                self.emit_output(
                    robot_reply_event_content(tool_args, result_text),
                    ROBOT_QQ_REPLY_EVENT_TYPE,
                    {
                        "tool_name": tool_name,
                        "qq_delivery": True,
                    },
                )
            if pending_reply_sent:
                self.emit_status("idle", "")
                return None
            auto_routed_to_job = is_tool_result_auto_routed_to_job(result)
            command_dispatch_failed = is_command_dispatch_failure_result(tool_name, result_text)
            command_dispatch_pending = is_command_dispatch_pending_result(tool_name, result_text)
            if result_text and not hide_tool_details and not command_dispatch_pending:
                self.emit_output(
                    result_text,
                    "agent_tool_result",
                    {"tool_name": tool_name},
                )

            if command_dispatch_failed:
                record_pending_terminal_continuation(
                    item_id=self.item_id,
                    command=str(tool_args.get("command") or ""),
                    reason="terminal_not_connected",
                    message=COMMAND_DISPATCH_FAILURE_MESSAGE,
                    tool_name=tool_name,
                )
                self.emit_output(
                    COMMAND_DISPATCH_FAILURE_MESSAGE,
                    "agent_warning",
                    {"tool_name": tool_name},
                )
                return None

            if is_background_job_started_result(result):
                task_workflow_manager.mark_job_started(
                    reply_ticket_id,
                    command=str(tool_args.get("command") or ""),
                )
                clear_pending_terminal_continuation(
                    self.item_id,
                    command=str(tool_args.get("command") or ""),
                )
                return None

            if tool_name != "mcp_local_update_task_workflow":
                task_workflow_manager.record_tool_result(
                    reply_ticket_id,
                    tool_name=tool_name,
                    success=bool(result.get("success", True))
                    and not result_text.lower().startswith("error:"),
                    result_summary=result_text,
                )

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

            if auto_routed_to_job:
                should_stop_after_tool, reason_after_tool = turn_guard.record_progress(
                    f"job:{normalized_tool_args_str}"
                )
            else:
                should_stop_after_tool, reason_after_tool = turn_guard.after_tool(
                    tool_name,
                    result_text,
                )
            if (
                tool_name in COMMAND_TOOL_NAMES
                and result.get("success")
                and not auto_routed_to_job
            ):
                clear_pending_terminal_continuation(
                    self.item_id,
                    command=str(tool_args.get("command") or ""),
                )
                self._set_pending_command(tool_name, tool_args)
                self._emit_waiting_terminal_status(tool_name)
                return None

            if auto_routed_to_job:
                clear_pending_terminal_continuation(
                    self.item_id,
                    command=str(tool_args.get("command") or ""),
                )

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
