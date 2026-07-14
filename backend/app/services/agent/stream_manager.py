import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.services.agent.terminal_noise import is_progress_noise_content
from app.services.agent.session import (
    InputMessage,
    InputType,
    agent_session_manager,
)

logger = logging.getLogger(__name__)

COMMAND_WAIT_TIMEOUT = 20
MAX_COMMANDS_PER_SESSION = 5
SESSION_TIMEOUT = 120
TERMINAL_BATCH_DEBOUNCE_SECONDS = 0.25
MIN_TERMINAL_BATCH_WINDOW_SECONDS = 0.4
MAX_TERMINAL_BATCH_WINDOW_SECONDS = 1.2
WAITING_TERMINAL_BATCH_DEBOUNCE_SECONDS = 0.08


@dataclass
class AgentWaitWindow:
    send_time: datetime
    query: str = ""
    waiting: bool = True
    command_count: int = 0
    session_start: datetime = field(default_factory=datetime.now)


@dataclass
class PendingTerminalBatch:
    item_id: str
    handler_id: str
    parts: list[str] = field(default_factory=list)
    raw_parts: list[str] = field(default_factory=list)
    query: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_update: datetime = field(default_factory=datetime.now)
    timer: threading.Timer | None = None


class TerminalStreamManager:
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

        self._agent_windows: dict[str, AgentWaitWindow] = {}
        self._chat_callbacks: dict[str, set[Callable]] = {}
        self._chat_lock = threading.RLock()
        self._terminal_batches: dict[str, PendingTerminalBatch] = {}
        self._terminal_batch_lock = threading.RLock()

        logger.info("[TerminalStreamManager] Initialized")

    def register_chat(self, item_id: str, callback: Callable):
        with self._chat_lock:
            callbacks = self._chat_callbacks.setdefault(item_id, set())
            callbacks.add(callback)

        session = agent_session_manager.get_session(item_id)
        if session:
            session.add_output_callback(callback)

    def unregister_chat(self, item_id: str, callback: Callable):
        with self._chat_lock:
            callbacks = self._chat_callbacks.get(item_id)
            if callbacks and callback in callbacks:
                callbacks.remove(callback)
                if not callbacks:
                    self._chat_callbacks.pop(item_id, None)

        session = agent_session_manager.get_session(item_id)
        if session:
            session.remove_output_callback(callback)

    def _get_callbacks(self, item_id: str) -> list[Callable]:
        with self._chat_lock:
            return list(self._chat_callbacks.get(item_id, set()))

    def _emit_to_chat(self, item_id: str, event: dict):
        callbacks = self._get_callbacks(item_id)
        if not callbacks:
            logger.debug(f"[StreamManager] No chat subscribers for item {item_id}")
            return

        delivered = 0
        for callback in callbacks:
            try:
                callback(event)
                delivered += 1
            except Exception as exc:
                logger.error(f"[StreamManager] Error emitting to chat: {exc}")

        logger.info(
            f"[StreamManager] Emitted {event.get('type', 'event')} to {delivered} "
            f"chat subscriber(s) for item {item_id}"
        )

    def broadcast_chat_event(self, item_id: str, event: dict):
        if event:
            self._emit_to_chat(item_id, event)

    def broadcast_chat_message(
        self,
        item_id: str,
        message: str,
        msg_type: str = "agent_response",
        *,
        role: str | None = None,
        extra: dict | None = None,
        timestamp: str | None = None,
    ):
        event = {
            "type": msg_type,
            "content": message,
            "timestamp": timestamp or datetime.now().isoformat(),
        }
        if role:
            event["role"] = role
        if extra:
            event.update(extra)
        self.broadcast_chat_event(item_id, event)
        return event

    def open_agent_window(self, item_id: str, query: str = ""):
        existing = self._agent_windows.get(item_id)
        self._agent_windows[item_id] = AgentWaitWindow(
            send_time=datetime.now(),
            query=query,
            command_count=existing.command_count if existing else 0,
            session_start=existing.session_start if existing else datetime.now(),
        )

    def close_agent_window(self, item_id: str):
        if window := self._agent_windows.get(item_id):
            window.waiting = False

    def increment_command_count(self, item_id: str) -> int:
        if window := self._agent_windows.get(item_id):
            window.command_count += 1
            return window.command_count
        return 0

    def should_stop_session(self, item_id: str) -> tuple[bool, str]:
        window = self._agent_windows.get(item_id)
        if not window:
            return False, ""
        if window.command_count >= MAX_COMMANDS_PER_SESSION:
            return True, f"已达到最大命令次数限制 ({MAX_COMMANDS_PER_SESSION})"
        if (datetime.now() - window.session_start).total_seconds() > SESSION_TIMEOUT:
            return True, f"会话超时 ({SESSION_TIMEOUT}s)"
        return False, ""

    def reset_session(self, item_id: str):
        self._agent_windows.pop(item_id, None)
        self.clear_pending_stream(item_id)

    def is_in_agent_window(self, item_id: str) -> bool:
        window = self._agent_windows.get(item_id)
        if not window or not window.waiting:
            return False
        if (datetime.now() - window.send_time).total_seconds() > COMMAND_WAIT_TIMEOUT:
            window.waiting = False
            self.broadcast_chat_message(item_id, "命令执行超时", "agent_warning")
            return False
        return True

    def _append_terminal_part(self, batch: PendingTerminalBatch, content: str):
        normalized = content.strip("\n")
        if normalized:
            batch.parts.append(normalized)
            batch.last_update = datetime.now()

    def _append_raw_terminal_part(self, batch: PendingTerminalBatch, content: str):
        normalized = content.strip("\n")
        if normalized:
            batch.raw_parts.append(normalized)
            batch.last_update = datetime.now()

    def _combine_terminal_parts(self, parts: list[str]) -> str:
        return "\n".join(part for part in parts if part)

    def _get_terminal_flush_delay(
        self,
        batch: PendingTerminalBatch,
        debounce_seconds: float,
        *,
        waiting_for_command_feedback: bool,
    ) -> float:
        if waiting_for_command_feedback:
            return debounce_seconds

        age_seconds = max((datetime.now() - batch.created_at).total_seconds(), 0.0)
        remaining_min_window = max(MIN_TERMINAL_BATCH_WINDOW_SECONDS - age_seconds, 0.0)
        remaining_max_window = max(MAX_TERMINAL_BATCH_WINDOW_SECONDS - age_seconds, 0.0)

        desired_delay = max(remaining_min_window, debounce_seconds)
        if remaining_max_window <= 0:
            return 0.0

        return min(desired_delay, remaining_max_window)

    def _schedule_terminal_flush(
        self,
        item_id: str,
        debounce_seconds: float = TERMINAL_BATCH_DEBOUNCE_SECONDS,
        *,
        waiting_for_command_feedback: bool = False,
    ):
        with self._terminal_batch_lock:
            batch = self._terminal_batches.get(item_id)
            if not batch:
                return

            if batch.timer:
                batch.timer.cancel()

            delay_seconds = self._get_terminal_flush_delay(
                batch,
                debounce_seconds,
                waiting_for_command_feedback=waiting_for_command_feedback,
            )

            timer = threading.Timer(
                delay_seconds,
                self.flush_pending_stream,
                args=(item_id,),
            )
            timer.daemon = True
            batch.timer = timer
            timer.start()

    def clear_pending_stream(self, item_id: str):
        with self._terminal_batch_lock:
            batch = self._terminal_batches.pop(item_id, None)
            if batch and batch.timer:
                batch.timer.cancel()

    def flush_pending_stream(self, item_id: str):
        with self._terminal_batch_lock:
            batch = self._terminal_batches.pop(item_id, None)

        if not batch:
            return

        if batch.timer:
            batch.timer.cancel()

        combined_output = self._combine_terminal_parts(batch.parts)
        combined_raw_output = self._combine_terminal_parts(batch.raw_parts)
        if not combined_output and not combined_raw_output:
            return

        logger.info(
            f"[StreamManager] Flushing terminal batch for item={item_id}, "
            f"parts={len(batch.parts)}, raw_parts={len(batch.raw_parts)}, "
            f"output_len={len(combined_output)}, raw_len={len(combined_raw_output)}"
        )

        session = agent_session_manager.get_or_create_session(item_id, batch.handler_id)
        for callback in self._get_callbacks(item_id):
            session.add_output_callback(callback)

        input_msg = InputMessage(
            input_type=InputType.TERMINAL,
            content=combined_output,
            raw_content=combined_raw_output,
            query=batch.query,
        )
        session.process_input(input_msg)

    def process_stream(
        self,
        item_id: str,
        filtered_output: str,
        handler_id: str = None,
        *,
        raw_output: str = "",
    ):
        logger.debug(
            f"[StreamManager] process_stream: item={item_id}, handler={handler_id}, "
            f"output_len={len(filtered_output) if filtered_output else 0}"
        )

        if not handler_id:
            logger.warning(f"[StreamManager] No handler_id provided for item {item_id}")
            return

        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        for callback in self._get_callbacks(item_id):
            session.add_output_callback(callback)
        has_filtered_output = bool(filtered_output and filtered_output.strip())
        has_raw_output = bool(raw_output and raw_output.strip())
        if not has_filtered_output and not (has_raw_output and session.has_pending_command()):
            logger.debug("[StreamManager] No usable output for agent processing, skipping")
            return

        waiting_for_command_feedback = session.has_pending_command()
        progress_candidate = "\n".join(
            part for part in (filtered_output, raw_output) if part and part.strip()
        )
        if waiting_for_command_feedback and is_progress_noise_content(progress_candidate):
            logger.info(
                "[StreamManager] Suppressed progress-only terminal batch for item=%s",
                item_id,
            )
            session.discard_pending_terminal_feedback_delta()
            return

        debounce_seconds = (
            WAITING_TERMINAL_BATCH_DEBOUNCE_SECONDS
            if waiting_for_command_feedback
            else TERMINAL_BATCH_DEBOUNCE_SECONDS
        )
        if session.is_running_turn():
            queued_terminal_source = (
                "raw_feedback"
                if waiting_for_command_feedback and has_raw_output and not has_filtered_output
                else "filtered_output"
            )
            self.broadcast_chat_message(
                item_id,
                "后续命令反馈排队中"
                if queued_terminal_source == "raw_feedback"
                else "后续过滤终端输出排队中",
                "agent_status",
                extra={
                    "status": "queued",
                    "queue_size": session.input_queue.qsize(),
                    "terminal_source": queued_terminal_source,
                },
            )
        elif session.has_pending_command():
            session.mark_waiting_terminal_feedback()
        else:
            session.mark_collecting()

        with self._terminal_batch_lock:
            batch = self._terminal_batches.get(item_id)
            if batch is None:
                batch = PendingTerminalBatch(item_id=item_id, handler_id=handler_id)
                self._terminal_batches[item_id] = batch
            else:
                batch.handler_id = handler_id

            if has_filtered_output:
                self._append_terminal_part(batch, filtered_output)
            if has_raw_output:
                self._append_raw_terminal_part(batch, raw_output)

        self._schedule_terminal_flush(
            item_id,
            debounce_seconds=debounce_seconds,
            waiting_for_command_feedback=waiting_for_command_feedback,
        )


stream_manager = TerminalStreamManager()
