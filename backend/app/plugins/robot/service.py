from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import ceil

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import Item, Robot, RobotItem, User
from app.plugins.robot.conversation_memory import robot_conversation_memory
from app.services.agent.chat_runtime import ChatResponseResult, collect_chat_response

from .contracts import RobotDispatchResponse, RobotInboundMessage, RobotReplyTarget
from .debug_log import preview_text, record_robot_event
from .memory_scope import (
    memory_scope_for_content,
    memory_scope_rank,
    speaker_global_key_from_context,
)
from .message_chunks import is_group_reply_target, split_robot_message_for_target
from .platforms import (
    DEFAULT_REPLY_CONTEXT_WINDOW_SECONDS,
    get_robot_platform,
    get_robot_runtime_config,
    normalize_robot_platform_id,
)

logger = logging.getLogger(__name__)

CONVERSATION_TTL = timedelta(hours=6)
CONVERSATION_PROCESSING_MIN_TIMEOUT_SECONDS = 120
CONVERSATION_PROCESSING_MAX_TIMEOUT_SECONDS = 600
PENDING_CHAT_QUEUE_LIMIT = 5
PENDING_DIRECT_WAKE_TRIGGER_REASONS = frozenset({
    "mention_bot",
    "reply_to_bot",
    "private_chat",
})
TASK_CONTROL_MESSAGE_RE = re.compile(
    r"(先别|别下|不要下|暂停|取消|停一下|停止下载|换源|换个源|"
    r"换(?:个)?(?:国内|国外)?镜像|改用.{0,20}镜像|\b(?:pause|cancel|stop)\b)",
    re.IGNORECASE,
)
RECENT_LIVE_CONTEXT_ACTIVE_LINES = 6
RECENT_LIVE_CONTEXT_BASE_LINES = 4
RECENT_LIVE_CONTEXT_EXPANDED_LINES = 12
RECENT_LIVE_CONTEXT_LINES = RECENT_LIVE_CONTEXT_EXPANDED_LINES
DEFAULT_MAX_MESSAGE_LENGTH = 1200
REPLY_MESSAGE_TYPE_PRIVATE = "private"
REPLY_MESSAGE_TYPE_GROUP = "group"
REPLY_MESSAGE_TYPE_CHANNEL = "channel"
REPLY_MESSAGE_TYPE_COMMAND = "command"
REPLY_MESSAGE_TYPE_MENTION = "mention"
DEFAULT_REPLY_MESSAGE_TYPES = frozenset(
    {
        REPLY_MESSAGE_TYPE_PRIVATE,
        REPLY_MESSAGE_TYPE_COMMAND,
        REPLY_MESSAGE_TYPE_MENTION,
    }
)
ALLOWED_REPLY_MESSAGE_TYPES = frozenset(
    {
        REPLY_MESSAGE_TYPE_PRIVATE,
        REPLY_MESSAGE_TYPE_GROUP,
        REPLY_MESSAGE_TYPE_CHANNEL,
        REPLY_MESSAGE_TYPE_COMMAND,
        REPLY_MESSAGE_TYPE_MENTION,
    }
)
REPLY_MESSAGE_TYPE_DISABLED_REASON = "reply_message_type_disabled"
MENTION_MATCH_MODE_BOT = "bot"
DEFAULT_MENTION_MATCH_MODE = MENTION_MATCH_MODE_BOT
QQ_AGENT_IGNORED_CQ_TYPES = frozenset({"image"})
CQ_CODE_PATTERN = re.compile(r"\[CQ:([A-Za-z0-9_]+)(?:,[^\]]*)?\]")
CONTEXT_DEPENDENT_TEXT_RE = re.compile(
    r"("
    r"为什么|为啥|怎么回事|什么意思|啥意思|然后呢|后来呢|继续|接着|刚才|刚刚|上面|前面|之前|"
    r"这个|那个|这事|那事|这下|那现在|然后|所以呢|咋办|怎么办|怎么弄|怎么搞|"
    r"好了吗|完了吗|结束了吗|成功了吗|失败了吗|装好了吗|换好了吗|行了吗|可以了吗|"
    r"是不是|对不对|对吗|是吗|呢|吗|"
    r"\b(?:why|continue|again|then|that|this|it|he|she|done|ready|status|what about)\b"
    r")",
    re.IGNORECASE,
)
ALLOWED_MENTION_MATCH_MODES = frozenset(
    {
        MENTION_MATCH_MODE_BOT,
    }
)


@dataclass
class ConversationState:
    item_id: uuid.UUID
    updated_at: datetime


@dataclass
class RobotConversationController:
    generation: int
    updated_at: datetime
    expires_at: datetime | None = None
    processing_expires_at: datetime | None = None
    sleeping: bool = False
    processing: bool = False


@dataclass(frozen=True)
class RobotConversationGate:
    active: bool
    generation: int
    sleeping: bool = False
    processing: bool = False


@dataclass
class ResolvedRobotBinding:
    binding: RobotItem
    item: Item
    route_key: str


@dataclass
class RobotCommand:
    mode: str
    target: str | None
    text: str


@dataclass
class PendingRobotMemoryCandidate:
    candidate: object
    confidence: float
    observations: int
    updated_at: datetime


@dataclass(frozen=True)
class PendingRobotChatInput:
    item_id: uuid.UUID
    route_key: str
    message_text: str
    sender_key: str
    sender_label: str
    trigger_reason: str
    reply_target: RobotReplyTarget
    enqueued_at: datetime


@dataclass(frozen=True)
class PendingRobotTaskReply:
    pending_id: str
    item_id: uuid.UUID
    route_key: str
    command: str
    sender_key: str
    sender_label: str
    trigger_reason: str
    reply_target: RobotReplyTarget
    enqueued_at: datetime


@dataclass(frozen=True)
class QueuedRobotChatJob:
    robot_id: uuid.UUID
    robot_owner_id: uuid.UUID
    item_id: uuid.UUID
    route_key: str
    message: str
    sender_key: str
    reply_target: RobotReplyTarget
    conversation_key: str
    enqueued_at: datetime
    direct_reply_trigger: bool = False
    reply_context_active: bool = False
    conversation_generation: int = 0
    reply_requires_awake: bool = False
    message_text: str = ""
    trigger_reason: str = ""
    inbound_message: RobotInboundMessage | None = None
    reply_ticket_id: str = ""
    pending_reply_id: str = ""


class RobotServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RobotService:
    def __init__(self) -> None:
        self._conversation_routes: dict[tuple[str, str], ConversationState] = {}
        self._conversation_controllers: dict[tuple[str, str], RobotConversationController] = {}
        self._pending_memory_candidates: dict[tuple[str, str, str], PendingRobotMemoryCandidate] = {}
        self._pending_chat_inputs: dict[tuple[str, str], list[PendingRobotChatInput]] = {}
        self._pending_task_replies: dict[tuple[str, str], list[PendingRobotTaskReply]] = {}
        self._lock = threading.RLock()
        self._dispatch_queue: queue.Queue[QueuedRobotChatJob] = queue.Queue(
            maxsize=max(1, settings.ROBOT_BACKEND_DISPATCH_QUEUE_SIZE)
        )
        self._dispatch_workers_started = False
        self._dispatch_worker_count = 0
        self._dispatch_worker_lock = threading.Lock()

    def dispatch_queue_snapshot(self) -> dict[str, int]:
        return {
            "size": self._dispatch_queue.qsize(),
            "max_size": self._dispatch_queue.maxsize,
            "workers": self._dispatch_worker_count,
        }

    def _ensure_dispatch_workers(self) -> None:
        if self._dispatch_workers_started:
            return
        with self._dispatch_worker_lock:
            if self._dispatch_workers_started:
                return
            worker_count = max(2, min(settings.ROBOT_BACKEND_DISPATCH_WORKERS, 8))
            for index in range(worker_count):
                worker = threading.Thread(
                    target=self._dispatch_worker_loop,
                    name=f"termman-backend-robot-dispatch-{index}",
                    daemon=True,
                )
                worker.start()
            self._dispatch_worker_count = worker_count
            self._dispatch_workers_started = True

    def _enqueue_chat_job(self, job: QueuedRobotChatJob) -> bool:
        self._ensure_dispatch_workers()
        try:
            self._dispatch_queue.put_nowait(job)
        except queue.Full:
            return False
        return True

    def enqueue_background_job_result(
        self,
        *,
        robot_id: uuid.UUID | str,
        item_id: uuid.UUID | str,
        sender_key: str,
        reply_target: RobotReplyTarget | dict,
        conversation_key: str,
        conversation_generation: int = 0,
        message: str,
        pending_reply_id: str = "",
        reply_ticket_id: str = "",
    ) -> bool:
        if not message.strip():
            return False
        try:
            parsed_robot_id = (
                robot_id if isinstance(robot_id, uuid.UUID) else uuid.UUID(str(robot_id))
            )
            parsed_item_id = (
                item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
            )
        except (TypeError, ValueError):
            return False

        try:
            target = (
                reply_target
                if isinstance(reply_target, RobotReplyTarget)
                else RobotReplyTarget.model_validate(reply_target)
            )
        except Exception:
            return False
        resolved_conversation_key = conversation_key or self._conversation_key_from_target(
            target,
            sender_key,
        )
        if not resolved_conversation_key:
            return False

        with Session(engine) as session:
            robot = session.get(Robot, parsed_robot_id)
            item = session.get(Item, parsed_item_id)
            if robot is None or item is None:
                return False
            if not robot.is_enabled:
                return False
            job = QueuedRobotChatJob(
                robot_id=robot.id,
                robot_owner_id=robot.owner_id,
                item_id=item.id,
                route_key="background_job",
                message=message,
                sender_key=sender_key,
                reply_target=target.model_copy(deep=True),
                conversation_key=resolved_conversation_key,
                direct_reply_trigger=True,
                reply_context_active=False,
                conversation_generation=conversation_generation,
                reply_requires_awake=False,
                enqueued_at=self._now(),
                reply_ticket_id=str(reply_ticket_id or ""),
                pending_reply_id=str(pending_reply_id or ""),
            )

        queued = self._enqueue_chat_job(job)
        record_robot_event(
            str(parsed_robot_id),
            direction="backend_queue",
            event="background_job_result_queued" if queued else "background_job_result_dropped",
            status="ok" if queued else "ignored",
            message=preview_text(message),
            payload={
                "item_id": str(parsed_item_id),
                "conversation": resolved_conversation_key,
                "queue": self.dispatch_queue_snapshot(),
            },
        )
        return queued

    def register_background_job_reply(
        self,
        *,
        robot_id: uuid.UUID | str,
        item_id: uuid.UUID | str,
        sender_key: str,
        reply_target: RobotReplyTarget | dict,
        conversation_key: str,
        conversation_generation: int = 0,
        command: str,
    ) -> str | None:
        if not command.strip():
            return None
        try:
            parsed_robot_id = (
                robot_id if isinstance(robot_id, uuid.UUID) else uuid.UUID(str(robot_id))
            )
            parsed_item_id = (
                item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
            )
        except (TypeError, ValueError):
            return None

        try:
            target = (
                reply_target
                if isinstance(reply_target, RobotReplyTarget)
                else RobotReplyTarget.model_validate(reply_target)
            )
        except Exception:
            return None

        resolved_conversation_key = conversation_key or self._conversation_key_from_target(
            target,
            sender_key,
        )
        if not resolved_conversation_key:
            return None

        with Session(engine) as session:
            robot = session.get(Robot, parsed_robot_id)
            item = session.get(Item, parsed_item_id)
            if robot is None or item is None or not robot.is_enabled:
                return None
            route_key = "background_job"

        now = self._now()
        pending_id = uuid.uuid4().hex
        pending = PendingRobotTaskReply(
            pending_id=pending_id,
            item_id=parsed_item_id,
            route_key=route_key,
            command=command,
            sender_key=sender_key,
            sender_label=self._sender_label_from_reply_target(target, sender_key),
            trigger_reason="background_job",
            reply_target=target.model_copy(deep=True),
            enqueued_at=now,
        )
        key = self._pending_chat_key(parsed_robot_id, resolved_conversation_key)
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._get_or_create_controller_locked(
                parsed_robot_id,
                resolved_conversation_key,
                now,
            )
            controller.updated_at = now
            queue_items = list(self._pending_task_replies.get(key) or [])
            queue_items.append(pending)
            self._pending_task_replies[key] = queue_items[-PENDING_CHAT_QUEUE_LIMIT:]

        record_robot_event(
            str(parsed_robot_id),
            direction="backend_queue",
            event="background_job_reply_registered",
            status="ok",
            message=preview_text(command),
            payload={
                "item_id": str(parsed_item_id),
                "conversation": resolved_conversation_key,
                "pending_reply_id": pending_id,
                "generation": conversation_generation,
            },
        )
        return pending_id

    def clear_background_job_reply(
        self,
        *,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        pending_reply_id: str,
    ) -> None:
        if not pending_reply_id or not conversation_key:
            return
        key = self._pending_chat_key(robot_id, conversation_key)
        with self._lock:
            queue_items = list(self._pending_task_replies.get(key) or [])
            if not queue_items:
                return
            kept = [entry for entry in queue_items if entry.pending_id != pending_reply_id]
            if kept:
                self._pending_task_replies[key] = kept
            else:
                self._pending_task_replies.pop(key, None)

    def _dispatch_worker_loop(self) -> None:
        while True:
            job = self._dispatch_queue.get()
            try:
                self._process_chat_job(job)
            except Exception:
                logger.exception(
                    "[RobotService] Robot dispatch worker failed for robot=%s item=%s",
                    job.robot_id,
                    job.item_id,
                )
            finally:
                self._dispatch_queue.task_done()

    def _process_chat_job(self, job: QueuedRobotChatJob) -> None:
        queue_wait_seconds = (self._now() - job.enqueued_at).total_seconds()
        record_robot_event(
            str(job.robot_id),
            direction="backend_worker",
            event="dispatch_started",
            payload={
                "item_id": str(job.item_id),
                "route_key": job.route_key,
                "queue_wait_seconds": round(queue_wait_seconds, 3),
                "queue": self.dispatch_queue_snapshot(),
            },
        )

        with Session(engine) as session:
            robot = session.get(Robot, job.robot_id)
            item = session.get(Item, job.item_id)
            if robot is None or item is None:
                self._record_and_send_job_error(
                    job,
                    "Robot or item no longer exists.",
                )
                return

            try:
                dispatch_requires_awake = (
                    job.reply_requires_awake and not job.direct_reply_trigger
                )
                if not self.conversation_controller_allows_reply(
                    job.robot_id,
                    job.conversation_key,
                    job.conversation_generation,
                    requires_awake=dispatch_requires_awake,
                ):
                    record_robot_event(
                        str(job.robot_id),
                        direction="backend_worker",
                        event="dispatch_skipped_sleeping_conversation",
                        status="ignored",
                        payload={
                            "item_id": str(job.item_id),
                            "route_key": job.route_key,
                            "conversation": job.conversation_key,
                            "generation": job.conversation_generation,
                        },
                    )
                    return
                chat_message = self._prepare_queued_chat_message(
                    robot=robot,
                    item=item,
                    job=job,
                )
                response = asyncio.run(
                    self._chat_with_item(
                        session=session,
                        robot=robot,
                        item=item,
                        message=chat_message,
                        sender_key=job.sender_key,
                        reply_target=job.reply_target,
                        conversation_key=job.conversation_key,
                        conversation_generation=job.conversation_generation,
                        reply_requires_awake=job.reply_requires_awake,
                        reply_ticket_id=job.reply_ticket_id,
                    )
                )
                response_text = self._visible_agent_response_text(response)
                robot_message_sent = response.robot_message_sent
                if response_text and not robot_message_sent:
                    robot_message_sent = self._send_visible_agent_response(
                        job,
                        response_text,
                    )
                self._apply_reply_context_result(
                    robot,
                    job.conversation_key,
                    robot_message_sent=robot_message_sent,
                    reply_target=job.reply_target,
                    conversation_generation=job.conversation_generation or None,
                    sleep_when_no_reply=job.reply_context_active
                    and not job.direct_reply_trigger,
                )
                if robot_message_sent:
                    if job.pending_reply_id:
                        self.clear_background_job_reply(
                            robot_id=job.robot_id,
                            conversation_key=job.conversation_key,
                            pending_reply_id=job.pending_reply_id,
                        )
                    self._enqueue_pending_chat_followup(
                        robot=robot,
                        conversation_key=job.conversation_key,
                    )
                else:
                    self._enqueue_pending_chat_followup(
                        robot=robot,
                        conversation_key=job.conversation_key,
                        direct_wakeup_only=True,
                    )
            except RobotServiceError as exc:
                self._record_and_send_job_error(job, exc.message)
                return
            except HTTPException as exc:
                detail = (
                    exc.detail if isinstance(exc.detail, str) else "Robot dispatch failed"
                )
                self._record_and_send_job_error(job, detail)
                return
            except Exception as exc:
                logger.exception(
                    "[RobotService] Unexpected queued robot dispatch error for robot %s",
                    job.robot_id,
                )
                self._record_and_send_job_error(
                    job,
                    str(exc) or "Robot dispatch failed.",
                )
                return

        if not response_text:
            record_robot_event(
                str(job.robot_id),
                direction="backend_to_bridge",
                event="dispatch_completed",
                payload={
                    "item_id": str(job.item_id),
                    "route_key": job.route_key,
                    "robot_message_sent": robot_message_sent,
                    "queue": self.dispatch_queue_snapshot(),
                },
            )
            logger.info(
                "[RobotService] Queued agent completed robot=%s item=%s route=%s sent=%s",
                job.robot_id,
                job.item_id,
                job.route_key,
                robot_message_sent,
            )
            return

        record_robot_event(
            str(job.robot_id),
            direction="backend_to_bridge",
            event="dispatch_response",
            message=response_text,
            payload={
                "item_id": str(job.item_id),
                "route_key": job.route_key,
                "reply_delivery": "mcp_tool"
                if response.robot_message_sent
                else "service_fallback",
                "robot_message_sent": robot_message_sent,
                "queue": self.dispatch_queue_snapshot(),
            },
        )
        logger.info(
            "[RobotService] Queued agent response robot=%s item=%s route=%s text=%s",
            job.robot_id,
            job.item_id,
            job.route_key,
            preview_text(response_text),
        )

    def _send_visible_agent_response(
        self,
        job: QueuedRobotChatJob,
        response_text: str,
    ) -> bool:
        if not response_text.strip():
            return False
        if not self.conversation_controller_allows_completion_reply(
            job.robot_id,
            job.conversation_key,
            job.conversation_generation,
            requires_awake=job.reply_requires_awake,
        ):
            record_robot_event(
                str(job.robot_id),
                direction="backend_to_bridge",
                event="dispatch_visible_response_dropped_sleeping_conversation",
                status="ignored",
                message=preview_text(response_text),
                payload={
                    "item_id": str(job.item_id),
                    "route_key": job.route_key,
                    "conversation": job.conversation_key,
                    "generation": job.conversation_generation,
                },
            )
            return False

        try:
            from .bridge_client import robot_bridge_client

            robot_bridge_client.send_message(job.robot_id, job.reply_target, response_text)
        except Exception:
            logger.exception(
                "[RobotService] Failed to send visible agent response robot=%s",
                job.robot_id,
            )
            record_robot_event(
                str(job.robot_id),
                direction="backend_to_bridge",
                event="dispatch_visible_response_send_failed",
                status="error",
                message=preview_text(response_text),
                payload={
                    "item_id": str(job.item_id),
                    "route_key": job.route_key,
                    "conversation": job.conversation_key,
                },
            )
            return False

        self._remember_assistant_conversation_memory(
            job.robot_id,
            job.conversation_key,
            response_text,
        )
        return True

    def _visible_agent_response_text(self, response: ChatResponseResult) -> str:
        text = (response.content or "").strip()
        if not text:
            return ""
        from app.plugins.robot.internal_trace import (
            is_robot_internal_trace_text,
            sanitize_robot_visible_text,
        )

        text = sanitize_robot_visible_text(text)
        if not text or is_robot_internal_trace_text(text):
            return ""
        try:
            from app.plugins.robot.agent.integration import (
                is_robot_read_only_tool_result,
            )
            from app.services.agent.integrations import fallback_is_delivery_result

            if fallback_is_delivery_result(text) or is_robot_read_only_tool_result(text):
                return ""
        except Exception:
            pass
        return text

    def _prepare_queued_chat_message(
        self,
        *,
        robot: Robot,
        item: Item,
        job: QueuedRobotChatJob,
    ) -> str:
        inbound_message = job.inbound_message
        message_text = (job.message_text or "").strip()
        if inbound_message is None or not message_text:
            return job.message

        self._persist_inbound_long_term_memory(
            item_id=item.id,
            robot=robot,
            message=inbound_message,
            conversation_key=job.conversation_key,
            message_text=message_text,
        )
        return self._agent_message_with_context(
            inbound_message,
            message_text,
            trigger_reason=job.trigger_reason,
            impression_card=self._conversation_impression_card(
                item_id=item.id,
                robot=robot,
                conversation_key=job.conversation_key,
                sender_key=job.sender_key,
                reply_target=job.reply_target,
                query=message_text,
            ),
            live_context_card=self._recent_live_context_card(
                robot=robot,
                conversation_key=job.conversation_key,
                trigger_reason=job.trigger_reason,
                current_message_text=message_text,
            ),
        )

    def _record_and_send_job_error(
        self,
        job: QueuedRobotChatJob,
        message: str,
    ) -> None:
        self._clear_reply_context_window_for_key(
            job.robot_id,
            job.conversation_key,
            reason="dispatch_error",
            expected_generation=job.conversation_generation or None,
        )
        record_robot_event(
            str(job.robot_id),
            direction="backend_worker",
            event="dispatch_error",
            status="error",
            message=message,
            payload={
                "item_id": str(job.item_id),
                "route_key": job.route_key,
                "queue": self.dispatch_queue_snapshot(),
            },
        )
        if not self.conversation_controller_allows_completion_reply(
            job.robot_id,
            job.conversation_key,
            job.conversation_generation,
            requires_awake=job.reply_requires_awake,
        ):
            return
        try:
            from .bridge_client import robot_bridge_client

            robot_bridge_client.send_message(job.robot_id, job.reply_target, message)
        except Exception:
            logger.exception(
                "[RobotService] Failed to send queued dispatch error robot=%s",
                job.robot_id,
            )
        else:
            self._remember_assistant_conversation_memory(job.robot_id, job.conversation_key, message)

    def handle_inbound_message(
        self,
        session: Session,
        robot: Robot,
        message: RobotInboundMessage,
    ) -> RobotDispatchResponse:
        logger.info(
            "[RobotService] Inbound robot=%s sender=%s target=%s text=%s",
            robot.id,
            message.sender_key,
            message.reply_target.target_id,
            preview_text(message.text),
        )
        record_robot_event(
            str(robot.id),
            direction="bridge_to_backend",
            event="inbound_message",
            message=message.text,
            payload={
                "sender_key": message.sender_key,
                "target_type": message.reply_target.target_type,
                "target_id": message.reply_target.target_id,
                "reply_target": message.reply_target.model_dump(mode="json"),
            },
        )
        self._assert_robot_supported(robot)
        if not robot.is_enabled:
            return RobotDispatchResponse(success=True, ignored=True, reason="robot_disabled")

        direct_reply_trigger = self._message_directly_addresses_bot(message)
        conversation_key = self._conversation_key(message)
        text = (message.text or "").strip()
        if not text and not direct_reply_trigger:
            return RobotDispatchResponse(success=True, ignored=True, reason="empty_message")
        if not text and direct_reply_trigger:
            text = "[empty robot wakeup]"
        controller_gate = self._record_conversation_controller_inbound(
            robot,
            message,
            conversation_key,
            text,
            direct_reply_trigger=direct_reply_trigger,
        )
        reply_context_active = controller_gate.active
        command_parse_text = self._strip_leading_bot_mentions_for_command(message, text)
        command = self._parse_robot_command(command_parse_text)
        if command.mode == "chat" and command.target is None:
            command = RobotCommand(mode="chat", target=None, text=text)
        self._remember_inbound_conversation_memory(
            robot,
            message,
            conversation_key,
            self._agent_visible_message_text(text),
        )
        if self._message_requests_conversation_sleep(command_parse_text) and (
            direct_reply_trigger or reply_context_active or controller_gate.sleeping
        ):
            self.sleep_conversation_controller(
                robot.id,
                conversation_key,
                reason="user_sleep_command",
            )
            record_robot_event(
                str(robot.id),
                direction="backend",
                event="message_ignored",
                status="ignored",
                message=message.text,
                payload={
                    "reason": "sleep_command",
                    "conversation": conversation_key,
                },
            )
            return RobotDispatchResponse(
                success=True,
                ignored=True,
                reason="sleep_command",
            )
        if command.mode == "chat" and not (direct_reply_trigger or reply_context_active):
            record_robot_event(
                str(robot.id),
                direction="backend",
                event="message_ignored",
                status="ignored",
                message=message.text,
                payload={
                    "reason": "conversation_sleeping",
                    "conversation": conversation_key,
                    "direct_reply_trigger": direct_reply_trigger,
                    "reply_context_active": reply_context_active,
                },
            )
            return RobotDispatchResponse(
                success=True,
                ignored=True,
                reason="conversation_sleeping",
            )
        mention_match_mode = self._mention_match_mode(robot)
        reply_categories = self._reply_message_categories(
            message,
            command,
            direct_reply_trigger=direct_reply_trigger,
            reply_context_active=reply_context_active,
            mention_match_mode=mention_match_mode,
        )
        allowed_reply_types = self._allowed_reply_message_types(robot)
        if not allowed_reply_types.intersection(reply_categories):
            record_robot_event(
                str(robot.id),
                direction="backend",
                event="message_ignored",
                status="ignored",
                message=message.text,
                payload={
                    "reason": REPLY_MESSAGE_TYPE_DISABLED_REASON,
                    "reply_message_types": sorted(reply_categories),
                    "allowed_reply_message_types": sorted(allowed_reply_types),
                    "mention_match_mode": mention_match_mode,
                },
            )
            return RobotDispatchResponse(
                success=True,
                ignored=True,
                reason=REPLY_MESSAGE_TYPE_DISABLED_REASON,
            )
        reply_requires_awake = (
            (direct_reply_trigger or reply_context_active)
            and self._reply_context_window_seconds(robot) > 0
        )
        conversation_generation = 0

        try:
            resolved_binding, message_text = self._resolve_chat_binding(
                session,
                robot,
                command,
                conversation_key,
                fallback_sender_key=message.sender_key,
            )
            if command.mode != "send":
                message_text = self._agent_visible_message_text(message_text)
                if not message_text:
                    record_robot_event(
                        str(robot.id),
                        direction="backend",
                        event="message_ignored",
                        status="ignored",
                        message=message.text,
                        payload={
                            "reason": "media_message_ignored",
                            "conversation": conversation_key,
                        },
                    )
                    return RobotDispatchResponse(
                        success=True,
                        ignored=True,
                        reason="media_message_ignored",
                    )
            self._remember_conversation(
                robot.id,
                conversation_key,
                resolved_binding.item.id,
            )

            if command.mode == "send":
                self._remember_inbound_conversation_memory(
                    robot,
                    message,
                    conversation_key,
                    self._agent_visible_message_text(message_text),
                )
                success = self._write_to_item_terminal(resolved_binding.item.id, message_text)
                if not success:
                    raise RobotServiceError("终端未运行或后端尚未连接到该终端。")
                response_text = "已发送到终端。"
                self._clear_reply_context_window_for_key(
                    robot.id,
                    conversation_key,
                    reason="terminal_command",
                    expected_generation=conversation_generation or None,
                )
                record_robot_event(
                    str(robot.id),
                    direction="backend_to_item",
                    event="terminal_write",
                    message=message_text,
                    payload={
                        "item_id": str(resolved_binding.item.id),
                        "route_key": resolved_binding.route_key,
                    },
                )
                reply_chunks = self._reply_chunks_for_target(
                    robot,
                    message.reply_target,
                    response_text,
                )
                if reply_chunks:
                    self._remember_assistant_conversation_memory(
                        robot.id,
                        conversation_key,
                        response_text,
                    )
                return RobotDispatchResponse(
                    success=True,
                    ignored=False,
                    item_id=str(resolved_binding.item.id),
                    route_key=resolved_binding.route_key,
                    reply_chunks=reply_chunks,
                )

            trigger_reason = self._agent_trigger_reason(
                message,
                direct_reply_trigger=direct_reply_trigger,
                reply_context_active=reply_context_active,
                mention_match_mode=mention_match_mode,
            )
            task_control_message = bool(TASK_CONTROL_MESSAGE_RE.search(message_text))
            if (
                command.mode == "chat"
                and controller_gate.processing
                and reply_context_active
                and not task_control_message
            ):
                pending_size = self._record_pending_chat_input(
                    robot=robot,
                    conversation_key=conversation_key,
                    item_id=resolved_binding.item.id,
                    route_key=resolved_binding.route_key,
                    message_text=message_text,
                    sender_key=message.sender_key,
                    sender_label=self._sender_memory_label(message),
                    trigger_reason=trigger_reason,
                    reply_target=message.reply_target,
                )
                record_robot_event(
                    str(robot.id),
                    direction="backend_queue",
                    event="dispatch_deferred_pending_chat",
                    payload={
                        "item_id": str(resolved_binding.item.id),
                        "route_key": resolved_binding.route_key,
                        "conversation": conversation_key,
                        "pending_size": pending_size,
                    },
                )
                return RobotDispatchResponse(
                    success=True,
                    ignored=False,
                    item_id=str(resolved_binding.item.id),
                    route_key=resolved_binding.route_key,
                    reason="queued_pending",
                    reply_chunks=[],
                )

            if direct_reply_trigger or reply_context_active:
                conversation_generation = self._begin_reply_context_dispatch(
                    robot,
                    conversation_key,
                    metadata=message.reply_target.metadata,
                )

            queued_job = QueuedRobotChatJob(
                robot_id=robot.id,
                robot_owner_id=robot.owner_id,
                item_id=resolved_binding.item.id,
                route_key=resolved_binding.route_key,
                message=self._agent_message_with_context(
                    message,
                    message_text,
                    trigger_reason=trigger_reason,
                ),
                sender_key=message.sender_key,
                reply_target=message.reply_target.model_copy(deep=True),
                conversation_key=conversation_key,
                direct_reply_trigger=direct_reply_trigger,
                reply_context_active=reply_context_active,
                conversation_generation=conversation_generation,
                reply_requires_awake=reply_requires_awake,
                message_text=message_text,
                trigger_reason=trigger_reason,
                inbound_message=message.model_copy(deep=True),
                enqueued_at=self._now(),
            )
            if not self._enqueue_chat_job(queued_job):
                self._clear_reply_context_window_for_key(
                    robot.id,
                    conversation_key,
                    reason="dispatch_queue_full",
                    expected_generation=conversation_generation or None,
                )
                record_robot_event(
                    str(robot.id),
                    direction="backend_queue",
                    event="dispatch_dropped_queue_full",
                    status="ignored",
                    message="Robot backend dispatch queue is full; message dropped.",
                    payload={
                        "item_id": str(resolved_binding.item.id),
                        "route_key": resolved_binding.route_key,
                        "queue": self.dispatch_queue_snapshot(),
                    },
                )
                return RobotDispatchResponse(
                    success=True,
                    ignored=True,
                    item_id=str(resolved_binding.item.id),
                    route_key=resolved_binding.route_key,
                    reason="dispatch_queue_full",
                    reply_chunks=[],
                )

            response = RobotDispatchResponse(
                success=True,
                ignored=False,
                item_id=str(resolved_binding.item.id),
                route_key=resolved_binding.route_key,
                reason="queued",
                reply_chunks=[],
            )
            record_robot_event(
                str(robot.id),
                direction="backend_queue",
                event="dispatch_queued",
                payload={
                    "item_id": str(resolved_binding.item.id),
                    "route_key": resolved_binding.route_key,
                    "queue": self.dispatch_queue_snapshot(),
                    "conversation": conversation_key,
                    "direct_reply_trigger": direct_reply_trigger,
                    "reply_context_active": reply_context_active,
                },
            )
            logger.info(
                "[RobotService] Queued inbound robot=%s item=%s route=%s queue=%s",
                robot.id,
                resolved_binding.item.id,
                resolved_binding.route_key,
                self.dispatch_queue_snapshot(),
            )
            return response
        except RobotServiceError as exc:
            self._clear_reply_context_window_for_key(
                robot.id,
                conversation_key,
                reason="dispatch_error",
                expected_generation=conversation_generation or None,
            )
            record_robot_event(
                str(robot.id),
                direction="backend",
                event="dispatch_error",
                status="error",
                message=exc.message,
            )
            return RobotDispatchResponse(
                success=False,
                ignored=False,
                error=exc.message,
                reply_chunks=self._reply_chunks_for_target(
                    robot,
                    message.reply_target,
                    exc.message,
                ),
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Robot dispatch failed"
            self._clear_reply_context_window_for_key(
                robot.id,
                conversation_key,
                reason="dispatch_error",
                expected_generation=conversation_generation or None,
            )
            record_robot_event(
                str(robot.id),
                direction="backend",
                event="dispatch_error",
                status="error",
                message=detail,
            )
            return RobotDispatchResponse(
                success=False,
                ignored=False,
                error=detail,
                reply_chunks=self._reply_chunks_for_target(
                    robot,
                    message.reply_target,
                    detail,
                ),
            )
        except Exception as exc:
            logger.exception(
                "[RobotService] Unexpected inbound message error for robot %s",
                robot.id,
            )
            self._clear_reply_context_window_for_key(
                robot.id,
                conversation_key,
                reason="dispatch_error",
                expected_generation=conversation_generation or None,
            )
            record_robot_event(
                str(robot.id),
                direction="backend",
                event="dispatch_error",
                status="error",
                message=str(exc),
            )
            fallback = "机器人处理失败"
            return RobotDispatchResponse(
                success=False,
                ignored=False,
                error=str(exc),
                reply_chunks=self._reply_chunks_for_target(
                    robot,
                    message.reply_target,
                    fallback,
                ),
            )

    def dispatch_filtered_output(
        self,
        item_id: str,
        filtered_output: str,
        *,
        item_title: str | None = None,
    ) -> None:
        logger.debug(
            "[RobotService] Skipping terminal output dispatch to robot for item=%s",
            item_id,
        )

    def _pending_chat_key(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> tuple[str, str]:
        return (str(robot_id), conversation_key)

    def _record_pending_chat_input(
        self,
        *,
        robot: Robot,
        conversation_key: str,
        item_id: uuid.UUID,
        route_key: str,
        message_text: str,
        sender_key: str,
        sender_label: str,
        trigger_reason: str,
        reply_target: RobotReplyTarget,
    ) -> int:
        entry = PendingRobotChatInput(
            item_id=item_id,
            route_key=route_key,
            message_text=message_text,
            sender_key=sender_key,
            sender_label=sender_label or sender_key,
            trigger_reason=trigger_reason or "active_chat_window",
            reply_target=reply_target.model_copy(deep=True),
            enqueued_at=self._now(),
        )
        key = self._pending_chat_key(robot.id, conversation_key)
        with self._lock:
            queue_items = list(self._pending_chat_inputs.get(key) or [])
            queue_items.append(entry)
            evicted_count = max(0, len(queue_items) - PENDING_CHAT_QUEUE_LIMIT)
            if evicted_count:
                queue_items = queue_items[-PENDING_CHAT_QUEUE_LIMIT:]
            self._pending_chat_inputs[key] = queue_items
            pending_size = len(queue_items)

        if evicted_count:
            record_robot_event(
                str(robot.id),
                direction="backend_queue",
                event="pending_chat_evicted",
                status="ignored",
                payload={
                    "conversation": conversation_key,
                    "evicted_count": evicted_count,
                    "pending_size": pending_size,
                },
            )
        return pending_size

    def _drain_pending_chat_inputs(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> list[PendingRobotChatInput]:
        key = self._pending_chat_key(robot_id, conversation_key)
        with self._lock:
            entries = list(self._pending_chat_inputs.pop(key, []) or [])
        return entries

    def _prepend_pending_chat_inputs(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        entries: list[PendingRobotChatInput],
    ) -> None:
        if not entries:
            return
        key = self._pending_chat_key(robot_id, conversation_key)
        with self._lock:
            queue_items = list(entries) + list(self._pending_chat_inputs.get(key) or [])
            self._pending_chat_inputs[key] = queue_items[-PENDING_CHAT_QUEUE_LIMIT:]

    def _pending_chat_snapshot_locked(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> tuple[list[dict[str, object]], uuid.UUID | None]:
        key = self._pending_chat_key(robot_id, conversation_key)
        entries = list(self._pending_chat_inputs.get(key) or [])
        task_replies = list(self._pending_task_replies.get(key) or [])
        snapshots: list[dict[str, object]] = []
        first_item_id: uuid.UUID | None = None
        index = 1
        for entry in entries[:PENDING_CHAT_QUEUE_LIMIT]:
            if first_item_id is None:
                first_item_id = entry.item_id
            text = re.sub(
                r"\s+",
                " ",
                self._agent_visible_message_text(entry.message_text),
            ).strip()
            if len(text) > 180:
                text = f"{text[:177]}..."
            snapshots.append(
                {
                    "index": index,
                    "item_id": str(entry.item_id),
                    "route_key": entry.route_key,
                    "sender_key": entry.sender_key,
                    "sender_label": entry.sender_label,
                    "trigger_reason": entry.trigger_reason,
                    "message_preview": text,
                    "enqueued_at": entry.enqueued_at.isoformat(),
                    "direct_wakeup": self._pending_chat_entry_is_direct_wakeup(entry),
                }
            )
            index += 1
        remaining_slots = max(0, PENDING_CHAT_QUEUE_LIMIT - len(snapshots))
        for task_reply in task_replies[:remaining_slots]:
            if first_item_id is None:
                first_item_id = task_reply.item_id
            command = re.sub(r"\s+", " ", task_reply.command).strip()
            if len(command) > 140:
                command = f"{command[:137]}..."
            snapshots.append(
                {
                    "index": index,
                    "item_id": str(task_reply.item_id),
                    "route_key": task_reply.route_key,
                    "sender_key": task_reply.sender_key,
                    "sender_label": task_reply.sender_label,
                    "trigger_reason": task_reply.trigger_reason,
                    "message_preview": f"后台 Job 完成后回复这个 QQ 会话：{command}",
                    "enqueued_at": task_reply.enqueued_at.isoformat(),
                    "direct_wakeup": True,
                    "pending_reply_id": task_reply.pending_id,
                    "command_preview": command,
                }
            )
            index += 1
        return snapshots, first_item_id

    def _agent_visible_message_text(self, message_text: str) -> str:
        def replace_ignored_cq(match: re.Match[str]) -> str:
            cq_type = match.group(1).strip().lower()
            if cq_type in QQ_AGENT_IGNORED_CQ_TYPES:
                return " "
            return match.group(0)

        sanitized = CQ_CODE_PATTERN.sub(replace_ignored_cq, message_text or "")
        sanitized = re.sub(r"[ \t\r\f\v]+", " ", sanitized)
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
        return sanitized.strip()

    def _pending_chat_entry_is_direct_wakeup(self, entry: PendingRobotChatInput) -> bool:
        return entry.trigger_reason in PENDING_DIRECT_WAKE_TRIGGER_REASONS

    def _pending_chat_batch_text(self, entries: list[PendingRobotChatInput]) -> str:
        lines = [
            "[Pending QQ messages; answer each unanswered item in order]",
            "These messages arrived while the bot was already thinking. Treat them as current live QQ messages, not old log history.",
        ]
        index = 1
        for entry in entries[:PENDING_CHAT_QUEUE_LIMIT]:
            text = re.sub(
                r"\s+", " ", self._agent_visible_message_text(entry.message_text)
            ).strip()
            if not text:
                continue
            if len(text) > 220:
                text = f"{text[:217]}..."
            lines.append(
                f"{index}. sender={entry.sender_label}; trigger={entry.trigger_reason}: {text}"
            )
            index += 1
        lines.append(
            "Reply in the current QQ conversation. If multiple people asked, answer them one by one in the same order."
        )
        return "\n".join(lines)

    def _enqueue_pending_chat_followup(
        self,
        *,
        robot: Robot,
        conversation_key: str,
        direct_wakeup_only: bool = False,
    ) -> bool:
        entries = [
            replace(entry, message_text=visible_text)
            for entry in self._drain_pending_chat_inputs(robot.id, conversation_key)
            for visible_text in [self._agent_visible_message_text(entry.message_text)]
            if visible_text
            and (not direct_wakeup_only or self._pending_chat_entry_is_direct_wakeup(entry))
        ]
        if not entries:
            return False

        for entry in entries:
            self._persist_inbound_long_term_memory(
                item_id=entry.item_id,
                robot=robot,
                message=RobotInboundMessage(
                    sender_key=entry.sender_key,
                    text=entry.message_text,
                    reply_target=entry.reply_target.model_copy(deep=True),
                ),
                conversation_key=conversation_key,
                message_text=entry.message_text,
            )

        latest = entries[-1]
        batch_text = self._pending_chat_batch_text(entries)
        live_context_card = self._recent_live_context_card(
            robot=robot,
            conversation_key=conversation_key,
            lines=RECENT_LIVE_CONTEXT_EXPANDED_LINES,
            trigger_reason="pending_queue",
            current_message_text=latest.message_text,
            excluded_message_texts=[entry.message_text for entry in entries],
        )
        synthetic_message = RobotInboundMessage(
            sender_key=latest.sender_key,
            text=latest.message_text,
            reply_target=latest.reply_target.model_copy(deep=True),
        )
        conversation_generation = self._begin_reply_context_dispatch(
            robot,
            conversation_key,
            metadata=latest.reply_target.metadata,
        )
        queued_job = QueuedRobotChatJob(
            robot_id=robot.id,
            robot_owner_id=robot.owner_id,
            item_id=latest.item_id,
            route_key=latest.route_key,
            message=self._agent_message_with_context(
                synthetic_message,
                batch_text,
                trigger_reason="pending_queue",
                impression_card=self._conversation_impression_card(
                    item_id=latest.item_id,
                    robot=robot,
                    conversation_key=conversation_key,
                    sender_key=latest.sender_key,
                    reply_target=latest.reply_target,
                    query=batch_text,
                ),
                live_context_card=live_context_card,
            ),
            sender_key=latest.sender_key,
            reply_target=latest.reply_target.model_copy(deep=True),
            conversation_key=conversation_key,
            direct_reply_trigger=False,
            reply_context_active=True,
            conversation_generation=conversation_generation,
            reply_requires_awake=self._reply_context_window_seconds(robot) > 0,
            enqueued_at=self._now(),
        )
        if not self._enqueue_chat_job(queued_job):
            self._prepend_pending_chat_inputs(robot.id, conversation_key, entries)
            self._clear_reply_context_window_for_key(
                robot.id,
                conversation_key,
                reason="pending_dispatch_queue_full",
                expected_generation=conversation_generation or None,
            )
            record_robot_event(
                str(robot.id),
                direction="backend_queue",
                event="pending_dispatch_dropped_queue_full",
                status="ignored",
                payload={
                    "item_id": str(latest.item_id),
                    "route_key": latest.route_key,
                    "conversation": conversation_key,
                    "pending_size": len(entries),
                    "queue": self.dispatch_queue_snapshot(),
                },
            )
            return False

        record_robot_event(
            str(robot.id),
            direction="backend_queue",
            event="pending_dispatch_queued",
            payload={
                "item_id": str(latest.item_id),
                "route_key": latest.route_key,
                "conversation": conversation_key,
                "pending_size": len(entries),
                "queue": self.dispatch_queue_snapshot(),
            },
        )
        return True

    def _recent_live_context_card(
        self,
        *,
        robot: Robot,
        conversation_key: str,
        lines: int | None = None,
        trigger_reason: str = "",
        current_message_text: str = "",
        excluded_message_texts: list[str] | None = None,
    ) -> str:
        if not conversation_key:
            return ""
        line_budget, strategy, hint = self._recent_live_context_budget(
            current_message_text,
            trigger_reason=trigger_reason,
            requested_lines=lines,
        )
        if line_budget <= 0:
            return ""
        try:
            from app.plugins.robot.internal_trace import sanitize_robot_visible_text

            recent = self._agent_visible_message_text(
                sanitize_robot_visible_text(
                    robot_conversation_memory.read_recent(
                        robot.id,
                        conversation_key,
                        lines=line_budget,
                    )
                )
            ).strip()
        except Exception:
            logger.debug(
                "[RobotService] Failed to read recent live context robot=%s conversation=%s",
                robot.id,
                conversation_key,
                exc_info=True,
            )
            return ""
        if not recent:
            return ""
        recent_lines = self._recent_context_lines_without_current(
            recent,
            current_message_text=current_message_text,
            excluded_message_texts=excluded_message_texts,
        )
        if not recent_lines:
            return ""
        return (
            "[Recent QQ live context; background only, progressive budget, "
            "answer only current/pending messages]\n"
            f"- context_budget: {strategy}; latest {line_budget} line(s) only\n"
            f"- context_hint: {hint}\n"
            + "\n".join(recent_lines)
        )

    def _recent_live_context_budget(
        self,
        message_text: str,
        *,
        trigger_reason: str = "",
        requested_lines: int | None = None,
    ) -> tuple[int, str, str]:
        if requested_lines is not None:
            line_budget = max(0, min(int(requested_lines), RECENT_LIVE_CONTEXT_LINES))
            if line_budget <= 0:
                return 0, "off", "caller disabled recent context"
            return (
                line_budget,
                "requested",
                "caller requested a fixed recent-context budget",
            )

        if self._message_needs_progressive_context(message_text):
            return (
                RECENT_LIVE_CONTEXT_EXPANDED_LINES,
                "expanded",
                "current QQ message is short, referential, or asks about prior status/context",
            )

        if trigger_reason == "active_chat_window":
            return (
                RECENT_LIVE_CONTEXT_ACTIVE_LINES,
                "active_window",
                "active wake window needs a small same-conversation sample to decide reply vs sleep",
            )

        return (
            RECENT_LIVE_CONTEXT_BASE_LINES,
            "baseline",
            "keep a small same-conversation window for natural continuity",
        )

    @staticmethod
    def _message_needs_progressive_context(message_text: str) -> bool:
        compact = re.sub(
            r"[\s\uFF0C\u3002\uFF01\uFF1F!,.\u3001~\uFF5E\u2026]+",
            "",
            str(message_text or "").strip(),
        )
        if not compact:
            return False
        if CONTEXT_DEPENDENT_TEXT_RE.search(compact):
            return True
        if len(compact) <= 8 and compact not in {"你好", "hello", "hi", "在吗"}:
            return True
        return False

    def _recent_context_lines_without_current(
        self,
        recent: str,
        *,
        current_message_text: str = "",
        excluded_message_texts: list[str] | None = None,
    ) -> list[str]:
        recent_lines = [line for line in str(recent or "").splitlines() if line.strip()]
        excluded_texts = {
            self._normalize_live_context_message_text(value)
            for value in (excluded_message_texts or [])
            if self._normalize_live_context_message_text(value)
        }
        if excluded_texts:
            return [
                line
                for line in recent_lines
                if self._normalize_live_context_message_text(
                    self._conversation_memory_line_text(line)
                )
                not in excluded_texts
            ]
        current_text = self._normalize_live_context_message_text(current_message_text)
        if recent_lines and current_text:
            last_line_text = self._normalize_live_context_message_text(
                self._conversation_memory_line_text(recent_lines[-1])
            )
            if last_line_text == current_text:
                recent_lines = recent_lines[:-1]
        return recent_lines

    @staticmethod
    def _conversation_memory_line_text(line: str) -> str:
        match = re.match(
            r"^\[[^\]]+\]\s+(?:user|assistant|system)(?:\s+[^:]+)?:\s*(.*)$",
            str(line or "").strip(),
        )
        if match:
            return match.group(1).strip()
        return str(line or "").strip()

    @staticmethod
    def _normalize_live_context_message_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())

    def _remember_assistant_conversation_memory(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        message_text: str,
    ) -> None:
        from app.plugins.robot.internal_trace import sanitize_robot_visible_text

        message_text = sanitize_robot_visible_text(message_text)
        if not message_text.strip():
            return
        try:
            robot_conversation_memory.append_assistant_message(
                robot_id,
                conversation_key,
                message_text,
            )
        except Exception:
            logger.exception(
                "[RobotService] Failed to write assistant conversation memory robot=%s conversation=%s",
                robot_id,
                conversation_key,
            )

    def _remember_inbound_conversation_memory(
        self,
        robot: Robot,
        message: RobotInboundMessage,
        conversation_key: str,
        message_text: str,
    ) -> None:
        if not message_text.strip():
            return
        try:
            robot_conversation_memory.append_user_message(
                robot.id,
                conversation_key,
                message_text,
                sender=self._sender_memory_label(message),
            )
        except Exception:
            logger.exception(
                "[RobotService] Failed to write conversation memory robot=%s conversation=%s",
                robot.id,
                conversation_key,
            )

    def _persist_inbound_long_term_memory(
        self,
        *,
        item_id: uuid.UUID | str,
        robot: Robot,
        message: RobotInboundMessage,
        conversation_key: str,
        message_text: str,
    ) -> None:
        if not message_text.strip():
            return
        try:
            from app.services.agent.memory.vector_store import vector_store
            from app.services.agent.prompts import policy as memory_policy

            explicit_candidate = memory_policy.build_conversation_memory_candidate(
                message_text,
                "recorded",
            )
            if explicit_candidate is not None:
                self._persist_scoped_memory_candidate(
                    item_id=item_id,
                    robot=robot,
                    conversation_key=conversation_key,
                    sender_key=message.sender_key,
                    reply_target=message.reply_target,
                    candidate=explicit_candidate,
                    store=vector_store,
                    source="qq_robot",
                )
                return

            scored_candidate = memory_policy.build_auto_conversation_memory_candidate(
                message_text,
                "recorded",
                speaker_label=self._sender_memory_label(message),
                speaker_key=message.sender_key,
                conversation_key=conversation_key,
            )
            if scored_candidate is None:
                return

            if scored_candidate.confidence >= memory_policy.AUTO_MEMORY_DIRECT_THRESHOLD:
                self._persist_scoped_memory_candidate(
                    item_id=item_id,
                    robot=robot,
                    conversation_key=conversation_key,
                    sender_key=message.sender_key,
                    reply_target=message.reply_target,
                    candidate=scored_candidate.candidate,
                    store=vector_store,
                    source="qq_robot_auto",
                    extra_metadata={"type": "conversation_auto", "observations": 1},
                )
                return

            promoted_candidate, observations = self._record_pending_memory_candidate(
                robot=robot,
                conversation_key=conversation_key,
                scored_candidate=scored_candidate,
                repeat_threshold=memory_policy.AUTO_MEMORY_REPEAT_THRESHOLD,
            )
            if promoted_candidate is None:
                return

            self._persist_scoped_memory_candidate(
                item_id=item_id,
                robot=robot,
                conversation_key=conversation_key,
                sender_key=message.sender_key,
                reply_target=message.reply_target,
                candidate=promoted_candidate,
                store=vector_store,
                source="qq_robot_auto_promoted",
                extra_metadata={
                    "type": "conversation_auto_promoted",
                    "observations": observations,
                    "verified": False,
                },
            )
        except Exception:
            logger.exception(
                "[RobotService] Failed to write long-term robot memory robot=%s conversation=%s",
                robot.id,
                conversation_key,
            )

    def _persist_scoped_memory_candidate(
        self,
        *,
        item_id: uuid.UUID | str,
        robot: Robot,
        conversation_key: str,
        sender_key: str = "",
        reply_target: RobotReplyTarget | None = None,
        candidate: object,
        store: object,
        source: str,
        extra_metadata: dict[str, object] | None = None,
    ) -> str | None:
        from app.services.agent.prompts import policy as memory_policy

        memory_type = str(getattr(candidate, "memory_type", "") or "")
        content = str(getattr(candidate, "content", "") or "")
        speaker_global_key = speaker_global_key_from_context(sender_key, reply_target)
        metadata = {
            **dict(getattr(candidate, "metadata", {}) or {}),
            "source": source,
            "robot_id": str(robot.id),
            "robot_conversation_key": conversation_key,
            "conversation_key": conversation_key,
            "memory_scope": memory_scope_for_content(content, memory_type),
        }
        if sender_key:
            metadata.setdefault("speaker_key", sender_key)
        if speaker_global_key:
            metadata["speaker_global_key"] = speaker_global_key
        if extra_metadata:
            metadata.update(extra_metadata)
        return memory_policy.persist_memory_candidate(
            str(item_id),
            replace(candidate, metadata=metadata),
            store=store,
        )

    def _record_pending_memory_candidate(
        self,
        *,
        robot: Robot,
        conversation_key: str,
        scored_candidate: object,
        repeat_threshold: int,
    ) -> tuple[object | None, int]:
        now = self._now()
        promotion_key = str(getattr(scored_candidate, "promotion_key", "") or "").strip()
        if not promotion_key:
            return None, 0

        key = (str(robot.id), conversation_key, promotion_key)
        with self._lock:
            self._prune_pending_memory_candidates_locked(now)
            existing = self._pending_memory_candidates.get(key)
            observations = (existing.observations + 1) if existing is not None else 1
            confidence = max(
                float(getattr(scored_candidate, "confidence", 0.0) or 0.0),
                existing.confidence if existing is not None else 0.0,
            )
            candidate = getattr(scored_candidate, "candidate", None)
            if candidate is None:
                return None, observations
            if observations < max(2, repeat_threshold):
                self._pending_memory_candidates[key] = PendingRobotMemoryCandidate(
                    candidate=candidate,
                    confidence=confidence,
                    observations=observations,
                    updated_at=now,
                )
                return None, observations
            self._pending_memory_candidates.pop(key, None)
            return candidate, observations

    def _prune_pending_memory_candidates_locked(self, now: datetime) -> None:
        expired_after = now - CONVERSATION_TTL
        expired_keys = [
            key
            for key, candidate in self._pending_memory_candidates.items()
            if candidate.updated_at < expired_after
        ]
        for key in expired_keys:
            self._pending_memory_candidates.pop(key, None)

    def _sender_memory_label(self, message: RobotInboundMessage) -> str:
        sender_data = message.reply_target.metadata.get("sender")
        if isinstance(sender_data, dict):
            sender_id = str(sender_data.get("user_id") or "").strip()
            display_name = str(sender_data.get("display_name") or sender_data.get("card") or sender_data.get("nickname") or sender_id or "").strip()
            if display_name and sender_id and display_name != sender_id:
                return f"{display_name} ({sender_id})"
            return display_name or sender_id
        return message.sender_key

    def _sender_label_from_reply_target(
        self,
        reply_target: RobotReplyTarget,
        sender_key: str,
    ) -> str:
        sender_data = reply_target.metadata.get("sender")
        if isinstance(sender_data, dict):
            sender_id = str(sender_data.get("user_id") or "").strip()
            display_name = str(
                sender_data.get("display_name")
                or sender_data.get("card")
                or sender_data.get("nickname")
                or sender_id
                or ""
            ).strip()
            if display_name and sender_id and display_name != sender_id:
                return f"{display_name} ({sender_id})"
            if display_name or sender_id:
                return display_name or sender_id
        return sender_key

    def normalize_chat_alias(self, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = re.sub(r"\s+", "-", value.strip())
        normalized = re.sub(r"[^\w\-]+", "-", normalized, flags=re.UNICODE)
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-_")
        return normalized.lower() or None

    def build_route_key(self, item: Item, binding: RobotItem) -> str:
        return (
            self.normalize_chat_alias(binding.chat_alias)
            or self.normalize_chat_alias(item.title)
            or str(item.id)
        )

    def collect_route_keys(
        self,
        session: Session,
        robot_id: uuid.UUID,
        *,
        exclude_item_id: uuid.UUID | None = None,
    ) -> set[str]:
        keys: set[str] = set()
        for binding, item in self._load_robot_bindings(session, robot_id):
            if exclude_item_id and item.id == exclude_item_id:
                continue
            keys.add(self.build_route_key(item, binding))
        return keys

    def get_binding_route_key(
        self,
        session: Session,
        robot_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> str | None:
        for binding, item in self._load_robot_bindings(session, robot_id):
            if item.id == item_id:
                return self.build_route_key(item, binding)
        return None

    def _load_robot_bindings(
        self,
        session: Session,
        robot_id: uuid.UUID,
    ) -> list[tuple[RobotItem, Item]]:
        bindings = session.exec(select(RobotItem).where(RobotItem.robot_id == robot_id)).all()

        pairs: list[tuple[RobotItem, Item]] = []
        for binding in bindings:
            item = session.get(Item, binding.item_id)
            if item is not None:
                pairs.append((binding, item))
        return pairs

    def _resolve_chat_binding(
        self,
        session: Session,
        robot: Robot,
        command: RobotCommand,
        conversation_key: str,
        fallback_sender_key: str = "",
    ) -> tuple[ResolvedRobotBinding, str]:
        bindings = [
            ResolvedRobotBinding(
                binding=binding,
                item=item,
                route_key=self.build_route_key(item, binding),
            )
            for binding, item in self._load_robot_bindings(session, robot.id)
            if binding.allow_chat
        ]

        if not bindings:
            raise RobotServiceError("当前机器人没有可聊天的终端绑定")

        explicit_route_key = self.normalize_chat_alias(command.target)
        if explicit_route_key:
            for resolved in bindings:
                if (
                    resolved.route_key == explicit_route_key
                    or str(resolved.item.id) == command.target
                    or self.normalize_chat_alias(resolved.item.title) == explicit_route_key
                ):
                    if not command.text:
                        raise RobotServiceError("请在终端别名后补充内容")
                    return resolved, command.text
            raise RobotServiceError(f"没有找到路由 `{command.target}` 对应的终端")

        remembered_item_id = self._get_remembered_item_id(robot.id, conversation_key)
        if not remembered_item_id and fallback_sender_key:
            remembered_item_id = self._get_remembered_item_id(
                robot.id,
                fallback_sender_key,
            )
        if remembered_item_id:
            for resolved in bindings:
                if resolved.item.id == remembered_item_id:
                    return resolved, command.text

        default_bindings = [binding for binding in bindings if binding.binding.is_default_target]
        if len(default_bindings) == 1:
            return default_bindings[0], command.text

        if len(bindings) == 1:
            return bindings[0], command.text

        aliases = ", ".join(sorted(binding.route_key for binding in bindings))
        raise RobotServiceError(
            "当前机器人绑定了多个终端，请使用 "
            f"`/term <别名> <内容>` 发送。可用别名: {aliases}"
        )

    def _extract_route_key(self, text: str) -> tuple[str | None, str]:
        normalized = (text or "").strip()
        if not normalized:
            return None, ""

        command_match = re.match(
            r"^/(?:term|item|terminal)\s+(\S+)(?:\s+(.*))?$",
            normalized,
            flags=re.IGNORECASE,
        )
        if command_match:
            route_key = self.normalize_chat_alias(command_match.group(1))
            return route_key, (command_match.group(2) or "").strip()

        hash_match = re.match(r"^#(\S+)(?:\s+(.*))?$", normalized)
        if hash_match:
            route_key = self.normalize_chat_alias(hash_match.group(1))
            return route_key, (hash_match.group(2) or "").strip()

        return None, normalized

    def _bot_self_ids_from_message(self, message: RobotInboundMessage) -> set[str]:
        metadata = message.reply_target.metadata
        raw_ids = metadata.get("bot_self_ids")
        if not isinstance(raw_ids, list):
            return set()
        return {str(value).strip() for value in raw_ids if str(value or "").strip()}

    def _message_mentions_bot_self_id(self, message: RobotInboundMessage) -> bool:
        metadata = message.reply_target.metadata
        bot_self_ids = self._bot_self_ids_from_message(message)
        if not bot_self_ids:
            return bool(metadata.get("mentioned_bot"))

        mention_ids: set[str] = set()
        mentions = metadata.get("mentions")
        if isinstance(mentions, list):
            for mention in mentions:
                if not isinstance(mention, dict):
                    continue
                mention_id = str(
                    mention.get("qq") or mention.get("id") or mention.get("user_id") or ""
                ).strip()
                if mention_id:
                    mention_ids.add(mention_id)

        native_message = metadata.get("message")
        if isinstance(native_message, dict):
            segments = native_message.get("segments")
            if isinstance(segments, list):
                for segment in segments:
                    if not isinstance(segment, dict):
                        continue
                    if str(segment.get("type") or "").strip().lower() != "at":
                        continue
                    data = segment.get("data")
                    if not isinstance(data, dict):
                        continue
                    mention_id = str(
                        data.get("qq") or data.get("id") or data.get("user_id") or ""
                    ).strip()
                    if mention_id:
                        mention_ids.add(mention_id)
            raw_message = str(native_message.get("raw_message") or "")
            for match in re.finditer(r"\[CQ:at,([^\]]+)\]", raw_message):
                params = self._parse_cq_params(match.group(1))
                mention_id = str(
                    params.get("qq") or params.get("id") or params.get("user_id") or ""
                ).strip()
                if mention_id:
                    mention_ids.add(mention_id)

        for match in re.finditer(r"\[CQ:at,([^\]]+)\]", message.text or ""):
            params = self._parse_cq_params(match.group(1))
            mention_id = str(
                params.get("qq") or params.get("id") or params.get("user_id") or ""
            ).strip()
            if mention_id:
                mention_ids.add(mention_id)

        if mention_ids:
            return bool(mention_ids.intersection(bot_self_ids))

        return self._conversation_message_type(message) not in {
            REPLY_MESSAGE_TYPE_GROUP,
            REPLY_MESSAGE_TYPE_CHANNEL,
        } and bool(metadata.get("mentioned_bot"))

    def _strip_leading_bot_mentions_for_command(
        self,
        message: RobotInboundMessage,
        text: str,
    ) -> str:
        normalized = (text or "").strip()
        bot_self_ids = self._bot_self_ids_from_message(message)
        if not normalized or not bot_self_ids:
            return normalized

        while True:
            match = re.match(r"^\[CQ:at,([^\]]+)\]\s*", normalized)
            if not match:
                return normalized
            params = self._parse_cq_params(match.group(1))
            mention_id = str(
                params.get("qq") or params.get("id") or params.get("user_id") or ""
            ).strip()
            if mention_id not in bot_self_ids:
                return normalized
            normalized = normalized[match.end():].lstrip()

    def _parse_cq_params(self, raw_params: str) -> dict[str, str]:
        params: dict[str, str] = {}
        for part in raw_params.split(","):
            key, separator, value = part.partition("=")
            if separator:
                params[key.strip()] = value.strip()
        return params
    def _parse_robot_command(self, text: str) -> RobotCommand:
        normalized = (text or "").strip()
        if not normalized:
            return RobotCommand(mode="chat", target=None, text="")

        command_match = re.match(
            r"^/(term|item|terminal|send|write)\s+(\S+)(?:\s+(.*))?$",
            normalized,
            flags=re.IGNORECASE,
        )
        if command_match:
            verb = command_match.group(1).lower()
            mode = "send" if verb in {"send", "write"} else "term"
            return RobotCommand(
                mode=mode,
                target=command_match.group(2),
                text=(command_match.group(3) or "").strip(),
            )

        hash_match = re.match(r"^#(\S+)(?:\s+(.*))?$", normalized)
        if hash_match:
            return RobotCommand(
                mode="term",
                target=hash_match.group(1),
                text=(hash_match.group(2) or "").strip(),
            )

        return RobotCommand(mode="chat", target=None, text=normalized)

    def _allowed_reply_message_types(self, robot: Robot) -> set[str]:
        config = robot.config if isinstance(robot.config, dict) else {}
        options = config.get("options") if isinstance(config.get("options"), dict) else {}
        if "reply_message_types" not in options:
            return set(DEFAULT_REPLY_MESSAGE_TYPES)

        raw_types = options.get("reply_message_types")
        if not isinstance(raw_types, list):
            return set(DEFAULT_REPLY_MESSAGE_TYPES)

        return {
            normalized_type
            for value in raw_types
            if isinstance(value, str)
            for normalized_type in {value.strip().lower()}
            if normalized_type in ALLOWED_REPLY_MESSAGE_TYPES
        }

    def _mention_match_mode(self, robot: Robot) -> str:
        config = robot.config if isinstance(robot.config, dict) else {}
        options = config.get("options") if isinstance(config.get("options"), dict) else {}
        raw_mode = options.get("mention_match_mode")
        if not isinstance(raw_mode, str):
            return DEFAULT_MENTION_MATCH_MODE

        normalized_mode = raw_mode.strip().lower()
        if normalized_mode in ALLOWED_MENTION_MATCH_MODES:
            return normalized_mode
        return DEFAULT_MENTION_MATCH_MODE

    def _reply_context_window_seconds(self, robot: Robot) -> int:
        config = robot.config if isinstance(robot.config, dict) else {}
        options = config.get("options") if isinstance(config.get("options"), dict) else {}
        raw_value = options.get("reply_context_window_seconds")
        try:
            return max(0, int(raw_value if raw_value is not None else DEFAULT_REPLY_CONTEXT_WINDOW_SECONDS))
        except (TypeError, ValueError):
            return max(0, DEFAULT_REPLY_CONTEXT_WINDOW_SECONDS)

    def _message_directly_addresses_bot(self, message: RobotInboundMessage) -> bool:
        if self._conversation_message_type(message) == REPLY_MESSAGE_TYPE_PRIVATE:
            return True
        if bool(message.reply_target.metadata.get("replied_to_bot")):
            return True
        return self._message_mentions_bot_self_id(message)

    def _reply_context_key(
        self,
        robot: Robot,
        message: RobotInboundMessage,
    ) -> tuple[str, str]:
        return (str(robot.id), self._conversation_key(message))

    def _message_conversation_parts(
        self,
        message: RobotInboundMessage,
    ) -> tuple[str, str]:
        metadata = message.reply_target.metadata
        target_data = metadata.get("target")
        if not isinstance(target_data, dict):
            target_data = {}
        sender_data = metadata.get("sender")
        if not isinstance(sender_data, dict):
            sender_data = {}
        conversation_data = metadata.get("conversation")
        if not isinstance(conversation_data, dict):
            conversation_data = {}

        conversation_type = str(
            conversation_data.get("type")
            or conversation_data.get("conversation_type")
            or ""
        ).strip().lower()
        conversation_id = str(
            conversation_data.get("id")
            or conversation_data.get("conversation_id")
            or ""
        ).strip()
        if conversation_type and conversation_id:
            return conversation_type, conversation_id

        message_type = str(
            target_data.get("message_type")
            or sender_data.get("message_type")
            or ""
        ).strip().lower()
        group_id = str(
            target_data.get("group_id")
            or conversation_data.get("group_id")
            or ""
        ).strip()
        user_id = str(
            target_data.get("user_id")
            or sender_data.get("user_id")
            or conversation_data.get("user_id")
            or ""
        ).strip()

        if message_type == "private" or bool(target_data.get("private")):
            return REPLY_MESSAGE_TYPE_PRIVATE, (
                user_id
                or str(target_data.get("id") or message.reply_target.target_id or "").strip()
                or message.sender_key
            )
        if message_type == "group" or group_id:
            return REPLY_MESSAGE_TYPE_GROUP, (
                group_id
                or str(
                    target_data.get("parent_id")
                    or target_data.get("id")
                    or message.reply_target.target_id
                    or ""
                ).strip()
                or message.sender_key
            )
        if bool(target_data.get("channel")):
            return REPLY_MESSAGE_TYPE_CHANNEL, (
                str(
                    target_data.get("parent_id")
                    or target_data.get("id")
                    or message.reply_target.target_id
                    or ""
                ).strip()
                or message.sender_key
            )

        target_type = (message.reply_target.target_type or "").strip().lower()
        if target_type in {"private", "c2c", "direct", "direct_message", "friend"}:
            return REPLY_MESSAGE_TYPE_PRIVATE, (
                str(message.reply_target.target_id or "").strip()
                or user_id
                or message.sender_key
            )
        if target_type in {"channel", "guild", "guild_channel"}:
            return REPLY_MESSAGE_TYPE_CHANNEL, (
                str(message.reply_target.target_id or "").strip() or message.sender_key
            )
        if target_type == "group":
            return REPLY_MESSAGE_TYPE_GROUP, (
                str(message.reply_target.target_id or "").strip() or message.sender_key
            )

        if ":private:" in message.sender_key:
            tail = message.sender_key.rsplit(":private:", 1)[-1].split(":", 1)[0]
            return REPLY_MESSAGE_TYPE_PRIVATE, tail or message.sender_key
        if ":channel:" in message.sender_key:
            tail = message.sender_key.rsplit(":channel:", 1)[-1].split(":", 1)[0]
            return REPLY_MESSAGE_TYPE_CHANNEL, tail or message.sender_key
        if ":group:" in message.sender_key:
            tail = message.sender_key.rsplit(":group:", 1)[-1].split(":", 1)[0]
            return REPLY_MESSAGE_TYPE_GROUP, tail or message.sender_key
        return REPLY_MESSAGE_TYPE_GROUP, message.sender_key

    def _conversation_key(self, message: RobotInboundMessage) -> str:
        conversation_type, conversation_id = self._message_conversation_parts(message)
        return f"{conversation_type}:{conversation_id or message.sender_key}"

    def _conversation_key_from_target(
        self,
        target: RobotReplyTarget,
        sender_key: str,
    ) -> str:
        target_type = str(target.target_type or "").strip().lower()
        target_id = str(target.target_id or "").strip()
        if target_type == "private":
            return f"{REPLY_MESSAGE_TYPE_PRIVATE}:{target_id or sender_key}"
        if target_type == "channel":
            return f"{REPLY_MESSAGE_TYPE_CHANNEL}:{target_id or sender_key}"
        if target_type == "group":
            return f"{REPLY_MESSAGE_TYPE_GROUP}:{target_id or sender_key}"
        if target_type == "command":
            return f"{REPLY_MESSAGE_TYPE_COMMAND}:{target_id or sender_key}"
        return f"{target_type or REPLY_MESSAGE_TYPE_GROUP}:{target_id or sender_key}"

    def _conversation_controller_key(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> tuple[str, str]:
        return (str(robot_id), conversation_key)

    def _controller_is_awake_locked(
        self,
        controller: RobotConversationController,
        now: datetime,
    ) -> bool:
        if controller.sleeping:
            return False
        if controller.processing:
            processing_expires_at = controller.processing_expires_at or (
                controller.updated_at
                + timedelta(seconds=CONVERSATION_PROCESSING_MAX_TIMEOUT_SECONDS)
            )
            if processing_expires_at <= now:
                controller.expires_at = None
                controller.processing_expires_at = None
                controller.processing = False
                controller.sleeping = True
                controller.generation += 1
                controller.updated_at = now
                return False
            return True
        if controller.expires_at is None:
            return False
        if controller.expires_at <= now:
            controller.expires_at = None
            controller.processing_expires_at = None
            controller.sleeping = True
            controller.generation += 1
            controller.updated_at = now
            return False
        return True

    def _get_or_create_controller_locked(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        now: datetime,
    ) -> RobotConversationController:
        key = self._conversation_controller_key(robot_id, conversation_key)
        controller = self._conversation_controllers.get(key)
        if controller is None:
            controller = RobotConversationController(generation=0, updated_at=now)
            self._conversation_controllers[key] = controller
        return controller

    def _record_conversation_controller_inbound(
        self,
        robot: Robot,
        message: RobotInboundMessage,
        conversation_key: str,
        message_text: str,
        *,
        direct_reply_trigger: bool = False,
    ) -> RobotConversationGate:
        now = self._now()
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._get_or_create_controller_locked(
                robot.id,
                conversation_key,
                now,
            )
            if direct_reply_trigger and controller.sleeping:
                controller.sleeping = False
                controller.generation += 1
            active = self._controller_is_awake_locked(controller, now)
            if not active and not direct_reply_trigger:
                controller.sleeping = True
            controller.updated_at = now
            return RobotConversationGate(
                active=active,
                generation=controller.generation,
                sleeping=controller.sleeping,
                processing=bool(controller.processing and not controller.sleeping),
            )

    def _begin_reply_context_dispatch(
        self,
        robot: Robot,
        conversation_key: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> int:
        now = self._now()
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._get_or_create_controller_locked(
                robot.id,
                conversation_key,
                now,
            )
            controller.generation += 1
            controller.sleeping = False
            controller.processing = True
            controller.processing_expires_at = now + timedelta(
                seconds=self._controller_processing_timeout_seconds(robot)
            )
            controller.expires_at = None
            controller.updated_at = now
            generation = controller.generation
        metadata = metadata or {}
        record_robot_event(
            str(robot.id),
            direction="backend",
            event="conversation_controller_processing",
            payload={
                "conversation": conversation_key,
                "generation": generation,
                "mentioned_bot": bool(metadata.get("mentioned_bot")),
                "replied_to_bot": bool(metadata.get("replied_to_bot")),
            },
        )
        return generation

    def _is_reply_context_active(
        self,
        robot: Robot,
        message: RobotInboundMessage,
    ) -> bool:
        conversation_key = self._conversation_key(message)
        now = self._now()
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._conversation_controllers.get(
                self._conversation_controller_key(robot.id, conversation_key)
            )
            return bool(controller and self._controller_is_awake_locked(controller, now))

    def _remember_reply_context_window(
        self,
        robot: Robot,
        message: RobotInboundMessage,
    ) -> None:
        self._remember_reply_context_window_for_key(
            robot,
            self._conversation_key(message),
            metadata=message.reply_target.metadata,
        )

    def _remember_reply_context_window_for_key(
        self,
        robot: Robot,
        conversation_key: str,
        *,
        metadata: dict[str, object] | None = None,
        expected_generation: int | None = None,
    ) -> None:
        window_seconds = self._reply_context_window_seconds(robot)
        if window_seconds <= 0:
            self._clear_reply_context_window_for_key(
                robot.id,
                conversation_key,
                reason="reply_context_window_disabled",
                expected_generation=expected_generation,
            )
            return

        now = self._now()
        expires_at = now + timedelta(seconds=window_seconds)
        key = self._conversation_controller_key(robot.id, conversation_key)
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._get_or_create_controller_locked(
                robot.id,
                conversation_key,
                now,
            )
            if expected_generation is not None and controller.generation != expected_generation:
                return
            controller.expires_at = expires_at
            controller.processing_expires_at = None
            controller.sleeping = False
            controller.processing = False
            controller.updated_at = now
            generation = controller.generation
        metadata = metadata or {}
        record_robot_event(
            str(robot.id),
            direction="backend",
            event="reply_context_window_refreshed",
            payload={
                "conversation": key[1],
                "generation": generation,
                "window_seconds": window_seconds,
                "expires_at": expires_at.isoformat(),
                "mentioned_bot": bool(metadata.get("mentioned_bot")),
                "replied_to_bot": bool(metadata.get("replied_to_bot")),
            },
        )

    def _clear_reply_context_window_for_key(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        *,
        reason: str,
        expected_generation: int | None = None,
    ) -> bool:
        if not conversation_key:
            return False

        key = self._conversation_controller_key(robot_id, conversation_key)
        with self._lock:
            controller = self._conversation_controllers.get(key)
            if controller is None:
                removed = False
            elif expected_generation is not None and controller.generation != expected_generation:
                removed = False
            else:
                was_awake = controller.expires_at is not None or controller.processing
                controller.expires_at = None
                controller.processing_expires_at = None
                controller.processing = False
                controller.sleeping = True
                controller.generation += 1
                controller.updated_at = self._now()
                removed = was_awake
        if removed:
            record_robot_event(
                str(robot_id),
                direction="backend",
                event="reply_context_window_cleared",
                payload={
                    "conversation": conversation_key,
                    "reason": reason,
                },
            )
        return removed

    def sleep_conversation_controller(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        *,
        reason: str,
    ) -> bool:
        if not conversation_key:
            return False

        now = self._now()
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._get_or_create_controller_locked(
                robot_id,
                conversation_key,
                now,
            )
            changed = bool(
                controller.expires_at is not None
                or controller.processing
                or not controller.sleeping
            )
            controller.expires_at = None
            controller.processing_expires_at = None
            controller.processing = False
            controller.sleeping = True
            controller.generation += 1
            controller.updated_at = now
            generation = controller.generation
        record_robot_event(
            str(robot_id),
            direction="backend",
            event="conversation_controller_sleeping",
            payload={
                "conversation": conversation_key,
                "generation": generation,
                "reason": reason,
                "changed": changed,
            },
        )
        return True

    def reply_context_window_seconds(self, robot: Robot) -> int:
        return self._reply_context_window_seconds(robot)

    def conversation_controller_snapshots(
        self,
        robot_ids: set[uuid.UUID | str] | None = None,
        item_ids: set[uuid.UUID | str] | None = None,
    ) -> list[dict[str, object]]:
        allowed_robot_ids = (
            {str(robot_id) for robot_id in robot_ids} if robot_ids else None
        )
        allowed_item_ids = {str(item_id) for item_id in item_ids} if item_ids else None
        now = self._now()
        snapshots: list[dict[str, object]] = []
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            for (
                robot_id,
                conversation_key,
            ), controller in self._conversation_controllers.items():
                if allowed_robot_ids is not None and robot_id not in allowed_robot_ids:
                    continue
                route_state = self._conversation_routes.get((robot_id, conversation_key))
                route_item_id = route_state.item_id if route_state else None
                pending_messages, pending_item_id = self._pending_chat_snapshot_locked(
                    robot_id,
                    conversation_key,
                )
                effective_item_id = route_item_id or pending_item_id
                if (
                    allowed_item_ids is not None
                    and str(effective_item_id or "") not in allowed_item_ids
                ):
                    continue
                awake = self._controller_is_awake_locked(controller, now)
                processing = bool(controller.processing and not controller.sleeping)
                expires_at = controller.expires_at
                seconds_remaining = (
                    max(0, ceil((expires_at - now).total_seconds()))
                    if expires_at is not None
                    else 0
                )
                processing_expires_at = controller.processing_expires_at
                processing_seconds_remaining = (
                    max(0, ceil((processing_expires_at - now).total_seconds()))
                    if processing and processing_expires_at is not None
                    else 0
                )
                conversation_type, _, conversation_id = conversation_key.partition(":")
                snapshots.append(
                    {
                        "robot_id": robot_id,
                        "conversation_key": conversation_key,
                        "conversation_type": conversation_type,
                        "conversation_id": conversation_id,
                        "item_id": str(effective_item_id) if effective_item_id else None,
                        "status": (
                            "processing"
                            if processing
                            else "awake" if awake else "sleeping"
                        ),
                        "awake": awake,
                        "sleeping": not awake,
                        "processing": processing,
                        "generation": controller.generation,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                        "processing_expires_at": (
                            processing_expires_at.isoformat()
                            if processing_expires_at
                            else None
                        ),
                        "processing_seconds_remaining": processing_seconds_remaining,
                        "updated_at": controller.updated_at.isoformat(),
                        "seconds_remaining": seconds_remaining,
                        "pending_count": len(pending_messages),
                        "pending_messages": pending_messages,
                    }
                )

        snapshots.sort(
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )
        return snapshots

    def _apply_reply_context_result(
        self,
        robot: Robot,
        conversation_key: str,
        *,
        robot_message_sent: bool,
        reply_target: RobotReplyTarget,
        conversation_generation: int | None = None,
        sleep_when_no_reply: bool = False,
    ) -> None:
        if robot_message_sent:
            self._remember_reply_context_window_for_key(
                robot,
                conversation_key,
                metadata=reply_target.metadata,
                expected_generation=conversation_generation,
            )
            return

        if sleep_when_no_reply:
            self.sleep_conversation_controller(
                robot.id,
                conversation_key,
                reason="agent_no_reply_active_chat_window",
            )
            return

        self._clear_reply_context_window_for_key(
            robot.id,
            conversation_key,
            reason="agent_did_not_send_qq_message",
            expected_generation=conversation_generation,
        )

    def conversation_controller_allows_reply(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        conversation_generation: int,
        *,
        requires_awake: bool,
    ) -> bool:
        if not requires_awake:
            return True
        if not conversation_key or conversation_generation <= 0:
            return False

        now = self._now()
        key = self._conversation_controller_key(robot_id, conversation_key)
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._conversation_controllers.get(key)
            if controller is None or controller.generation != conversation_generation:
                return False
            return self._controller_is_awake_locked(controller, now)

    def conversation_controller_allows_completion_reply(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        conversation_generation: int,
        *,
        requires_awake: bool,
    ) -> bool:
        if not requires_awake:
            return True
        if not conversation_key or conversation_generation <= 0:
            return False

        now = self._now()
        key = self._conversation_controller_key(robot_id, conversation_key)
        with self._lock:
            self._prune_conversation_controllers_locked(now)
            controller = self._conversation_controllers.get(key)
            if controller is None or controller.generation != conversation_generation:
                return False
            if controller.sleeping:
                return False
            if controller.processing:
                return True
            return self._controller_is_awake_locked(controller, now)

    def _controller_processing_timeout_seconds(self, robot: Robot) -> int:
        window_seconds = max(0, self._reply_context_window_seconds(robot))
        return max(
            CONVERSATION_PROCESSING_MIN_TIMEOUT_SECONDS,
            min(CONVERSATION_PROCESSING_MAX_TIMEOUT_SECONDS, window_seconds * 12),
        )

    def _prune_conversation_controllers_locked(self, now: datetime) -> None:
        expired_after = now - CONVERSATION_TTL
        expired_keys = [
            key
            for key, controller in self._conversation_controllers.items()
            if controller.updated_at < expired_after
        ]
        for key in expired_keys:
            self._conversation_controllers.pop(key, None)

    def _reply_message_categories(
        self,
        message: RobotInboundMessage,
        command: RobotCommand,
        *,
        direct_reply_trigger: bool = False,
        reply_context_active: bool = False,
        mention_match_mode: str = DEFAULT_MENTION_MATCH_MODE,
    ) -> set[str]:
        message_type = self._conversation_message_type(message)
        categories: set[str] = set()
        if message_type == REPLY_MESSAGE_TYPE_PRIVATE:
            categories.add(REPLY_MESSAGE_TYPE_PRIVATE)
        elif message_type == REPLY_MESSAGE_TYPE_GROUP:
            categories.add(REPLY_MESSAGE_TYPE_GROUP)
        elif message_type == REPLY_MESSAGE_TYPE_CHANNEL:
            categories.add(REPLY_MESSAGE_TYPE_CHANNEL)
        if command.mode != "chat" or command.target:
            categories.add(REPLY_MESSAGE_TYPE_COMMAND)
        if direct_reply_trigger or reply_context_active:
            categories.add(REPLY_MESSAGE_TYPE_MENTION)
        return categories

    def _conversation_message_type(self, message: RobotInboundMessage) -> str:
        return self._message_conversation_parts(message)[0]

    def _message_has_mentions(self, message: RobotInboundMessage) -> bool:
        mentions = message.reply_target.metadata.get("mentions")
        if not isinstance(mentions, list):
            return False
        return any(
            isinstance(mention, dict)
            and bool(str(mention.get("id") or mention.get("qq") or "").strip())
            for mention in mentions
        )

    @staticmethod
    def _memory_timestamp_label(memory: dict[str, object]) -> str:
        metadata = memory.get("metadata") if isinstance(memory, dict) else {}
        if not isinstance(metadata, dict):
            return ""
        return str(metadata.get("updated_at") or metadata.get("created_at") or "")

    @staticmethod
    def _memory_expired(memory: dict[str, object]) -> bool:
        metadata = memory.get("metadata") if isinstance(memory, dict) else {}
        if not isinstance(metadata, dict):
            return False
        if str(metadata.get("memory_type") or "") in {"preference", "error"}:
            return False
        expires_at = metadata.get("expires_at")
        if not expires_at:
            return False
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return parsed < now

    @staticmethod
    def _memory_inactive(memory: dict[str, object]) -> bool:
        metadata = memory.get("metadata") if isinstance(memory, dict) else {}
        if not isinstance(metadata, dict):
            return False
        memory_type = str(metadata.get("memory_type") or "")
        status = str(metadata.get("status") or "").lower()
        return memory_type == "task" and status == "completed"

    @staticmethod
    def _memory_matches_robot_conversation(
        memory: dict[str, object],
        *,
        robot: Robot,
        conversation_key: str,
        speaker_global_key: str = "",
    ) -> bool:
        if not isinstance(memory, dict) or not conversation_key:
            return False
        return memory_scope_rank(
            memory,
            robot_id=str(robot.id),
            conversation_key=conversation_key,
            speaker_global_key=speaker_global_key,
        ) > 0

    @staticmethod
    def _impression_memory_sort_key(memory: dict[str, object]) -> tuple[int, int, str]:
        metadata = memory.get("metadata") if isinstance(memory, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        memory_type = str(metadata.get("memory_type") or "fact")
        type_rank = {
            "preference": 5,
            "fact": 4,
            "context": 3,
            "error": 2,
        }.get(memory_type, 1)
        verified_rank = 1 if metadata.get("verified") is True else 0
        updated_at = str(metadata.get("updated_at") or metadata.get("created_at") or "")
        return type_rank, verified_rank, updated_at

    def _conversation_impression_card(
        self,
        *,
        item_id: uuid.UUID | str,
        robot: Robot,
        conversation_key: str,
        sender_key: str = "",
        reply_target: RobotReplyTarget | None = None,
        query: str = "",
        limit: int = 6,
    ) -> str:
        if not conversation_key:
            return ""
        try:
            from app.plugins.robot.internal_trace import sanitize_robot_visible_text
            from app.services.agent.memory.vector_store import vector_store
        except Exception:
            logger.debug("[RobotService] Robot impression card dependencies unavailable")
            return ""

        speaker_global_key = speaker_global_key_from_context(sender_key, reply_target)
        vector_store.maintain_memories(str(item_id))
        try:
            all_memories = vector_store.get_all_memories(str(item_id))
        except Exception as exc:
            logger.debug(
                "[RobotService] Failed to load robot impression memories item=%s: %s",
                item_id,
                exc,
            )
            all_memories = []

        scoped_memories = [
            memory
            for memory in all_memories
            if isinstance(memory, dict)
            and not self._memory_expired(memory)
            and not self._memory_inactive(memory)
            and self._memory_matches_robot_conversation(
                memory,
                robot=robot,
                conversation_key=conversation_key,
                speaker_global_key=speaker_global_key,
            )
        ]
        if not scoped_memories:
            return ""

        query_text = re.sub(r"\s+", " ", str(query or "")).strip()
        relevant_memories: list[dict[str, object]] = []
        if query_text:
            try:
                recalled = vector_store.search_memories(
                    item_id=str(item_id),
                    query=query_text,
                    n_results=max(12, limit * 4),
                    include_expired=False,
                    active_only=True,
                    min_similarity=0.18,
                )
            except Exception as exc:
                logger.debug(
                    "[RobotService] Failed to query robot impression memories item=%s: %s",
                    item_id,
                    exc,
                )
                recalled = []
            relevant_memories = [
                memory
                for memory in recalled
                if isinstance(memory, dict)
                and self._memory_matches_robot_conversation(
                    memory,
                    robot=robot,
                    conversation_key=conversation_key,
                    speaker_global_key=speaker_global_key,
                )
            ]

        scoped_memories.sort(
            key=lambda memory: (
                memory_scope_rank(
                    memory,
                    robot_id=str(robot.id),
                    conversation_key=conversation_key,
                    speaker_global_key=speaker_global_key,
                ),
                *self._impression_memory_sort_key(memory),
            ),
            reverse=True,
        )
        relevant_memories.sort(
            key=lambda memory: (
                memory_scope_rank(
                    memory,
                    robot_id=str(robot.id),
                    conversation_key=conversation_key,
                    speaker_global_key=speaker_global_key,
                ),
                max(
                    0.0,
                    1.0
                    - float(
                        memory.get("distance")
                        if memory.get("distance") is not None
                        else 1.0
                    ),
                ),
                *self._impression_memory_sort_key(memory),
            ),
            reverse=True,
        )

        stable_memories = [
            memory
            for memory in scoped_memories
            if str((memory.get("metadata") or {}).get("memory_type") or "")
            in {"preference", "error"}
            or (memory.get("metadata") or {}).get("verified") is True
        ][:2]
        ordered_memories = [*stable_memories, *relevant_memories, *scoped_memories]
        lines = [
            "[Current QQ conversation impression card; background only, do not answer old items]"
        ]
        seen_content: set[str] = set()
        seen_ids: set[str] = set()
        for memory in ordered_memories:
            if len(lines) > limit:
                break
            memory_id = str(memory.get("id") or "")
            if memory_id and memory_id in seen_ids:
                continue
            metadata = memory.get("metadata") if isinstance(memory, dict) else {}
            if not isinstance(metadata, dict):
                metadata = {}
            content = sanitize_robot_visible_text(str(memory.get("content") or "")).strip()
            content = re.sub(r"\s+", " ", content)
            if (
                not content
                or content in seen_content
                or (query_text and content.casefold() == query_text.casefold())
            ):
                continue
            if memory_id:
                seen_ids.add(memory_id)
            seen_content.add(content)
            if len(content) > 160:
                content = f"{content[:157]}..."
            sender = str(
                metadata.get("speaker")
                or metadata.get("speaker_label")
                or metadata.get("sender")
                or ""
            ).strip()
            prefix = f"{sender}: " if sender and not content.startswith(sender) else ""
            lines.append(f"- {prefix}{content}")
        if len(lines) == 1:
            return ""
        return "\n".join(lines)
    def _message_requests_conversation_sleep(self, text: str) -> bool:
        normalized = (text or "").strip().casefold()
        if not normalized:
            return False
        compact = re.sub(
            r"[\s\uFF0C\u3002\uFF01\uFF1F!,.\u3001~\uFF5E\u2026]+",
            "",
            normalized,
        )
        return compact in {
            "/sleep",
            "sleep",
            "gosleep",
            "stopreplying",
            "shutup",
            "\u4f11\u7720",
            "\u4f11\u7720\u53bb",
            "\u53bb\u4f11\u7720",
            "\u7761\u89c9",
            "\u7761\u89c9\u53bb",
            "\u95ed\u5634",
            "\u522b\u8bf4\u8bdd",
            "\u522b\u56de\u4e86",
            "\u522b\u56de\u590d\u4e86",
            "\u4e0d\u7528\u56de\u4e86",
            "\u4e0d\u8981\u56de\u4e86",
            "\u505c\u6b62\u56de\u590d",
            "\u505c\u4e00\u4e0b",
            "\u5148\u522b\u56de",
            "\u5148\u522b\u56de\u590d",
            "\u5b89\u9759",
        }

    def _agent_message_with_context(
        self,
        inbound_message: RobotInboundMessage,
        message_text: str,
        *,
        trigger_reason: str = "",
        impression_card: str = "",
        live_context_card: str = "",
    ) -> str:
        prefix = self._agent_message_context_prefix(
            inbound_message,
            trigger_reason=trigger_reason,
        )
        if not prefix:
            return message_text
        parts = [prefix]
        sender_identity_card = self._agent_sender_identity_context_card(inbound_message)
        if sender_identity_card:
            parts.append(sender_identity_card)
        identity_card = self._agent_identity_context_card(
            inbound_message,
            trigger_reason=trigger_reason,
        )
        if identity_card:
            parts.append(identity_card)
        if impression_card.strip():
            parts.append(impression_card.strip())
        if live_context_card.strip():
            parts.append(live_context_card.strip())
        reply_reference_card = self._agent_reply_reference_context_card(inbound_message)
        if reply_reference_card:
            parts.append(reply_reference_card)
        parts.append(f"[Current QQ message]\n{message_text}")
        return "\n".join(parts)

    def _agent_sender_identity_context_card(
        self,
        message: RobotInboundMessage,
    ) -> str:
        sender_data = message.reply_target.metadata.get("sender")
        if not isinstance(sender_data, dict):
            return ""

        sender_id = str(
            sender_data.get("user_id")
            or sender_data.get("qq")
            or sender_data.get("id")
            or ""
        ).strip()
        display_name = str(
            sender_data.get("display_name")
            or sender_data.get("card")
            or sender_data.get("nickname")
            or sender_id
            or "unknown"
        ).strip()
        sender_label = display_name
        if sender_id and sender_id != display_name:
            sender_label = f"{display_name} ({sender_id})"

        return "\n".join(
            [
                "[Current QQ sender; authoritative for this turn]",
                f"- sender: {sender_label}",
                (
                    "- first_person_rule: In [Current QQ message], "
                    f"'我/我的/我是谁' refers to {sender_label}, not the bot "
                    "or another person from recent context."
                ),
            ]
        )

    def _agent_reply_reference_context_card(
        self,
        message: RobotInboundMessage,
    ) -> str:
        reply_data = message.reply_target.metadata.get("reply")
        if not isinstance(reply_data, dict):
            return ""

        lines = [
            "[Replied QQ message; background only, use it to resolve references in the current message]",
        ]
        message_id = str(
            reply_data.get("message_id") or reply_data.get("id") or ""
        ).strip()
        if message_id:
            lines.append(f"- message_id: {message_id}")

        sender_data = reply_data.get("sender")
        if isinstance(sender_data, dict):
            sender_label = self._reply_sender_label_for_context(sender_data)
            if sender_label:
                lines.append(f"- sender: {sender_label}")

        text = str(
            reply_data.get("text")
            or reply_data.get("plain_text")
            or reply_data.get("raw_message")
            or ""
        ).strip()
        if text:
            lines.append(f"- text: {text[:600].rstrip()}")
        elif message_id:
            lines.append("- text: unavailable; only the replied message id was provided")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _reply_sender_label_for_context(self, sender_data: dict[str, object]) -> str:
        sender_id = str(
            sender_data.get("user_id")
            or sender_data.get("qq")
            or sender_data.get("id")
            or ""
        ).strip()
        display_name = str(
            sender_data.get("display_name")
            or sender_data.get("card")
            or sender_data.get("nickname")
            or sender_id
            or ""
        ).strip()
        if sender_id and display_name and sender_id != display_name:
            return f"{display_name} ({sender_id})"
        return display_name or sender_id

    def _agent_identity_context_card(
        self,
        message: RobotInboundMessage,
        *,
        trigger_reason: str = "",
    ) -> str:
        bot_self_ids = sorted(self._bot_self_ids_from_message(message))
        if not bot_self_ids:
            return ""

        mentioned_self = self._message_mentions_bot_self_id(message)
        replied_to_self = bool(message.reply_target.metadata.get("replied_to_bot"))
        private_chat = self._conversation_message_type(message) == REPLY_MESSAGE_TYPE_PRIVATE
        addressed_to_bot = private_chat or mentioned_self or replied_to_self
        if trigger_reason:
            reason = trigger_reason
        elif replied_to_self:
            reason = "reply_to_bot"
        elif mentioned_self:
            reason = "mention_bot"
        elif private_chat:
            reason = "private_chat"
        else:
            reason = "none"

        self_id_label = ", ".join(bot_self_ids)
        return "\n".join(
            [
                "[Robot identity; background only]",
                f"- self_id: {self_id_label} (this QQ id is you, the bot)",
                f"- addressed_to_bot: {str(addressed_to_bot).lower()}",
                f"- direct_reason: {reason}",
                f"- mentioned_self: {str(mentioned_self).lower()}",
                f"- replied_to_self: {str(replied_to_self).lower()}",
                "- identity_rule: QQ mentions/replies to this self_id are addressing you.",
            ]
        )

    def _agent_trigger_reason(
        self,
        message: RobotInboundMessage,
        *,
        direct_reply_trigger: bool,
        reply_context_active: bool,
        mention_match_mode: str = DEFAULT_MENTION_MATCH_MODE,
    ) -> str:
        if bool(message.reply_target.metadata.get("replied_to_bot")):
            return "reply_to_bot"
        if bool(message.reply_target.metadata.get("mentioned_bot")):
            return "mention_bot"
        if self._conversation_message_type(message) == REPLY_MESSAGE_TYPE_PRIVATE:
            return "private_chat"
        if reply_context_active and not direct_reply_trigger:
            return "active_chat_window"
        return "plain"

    def _agent_message_context_prefix(
        self,
        message: RobotInboundMessage,
        *,
        trigger_reason: str = "",
    ) -> str:
        sender_data = message.reply_target.metadata.get("sender")
        if not isinstance(sender_data, dict):
            return ""

        target_data = message.reply_target.metadata.get("target")
        if not isinstance(target_data, dict):
            target_data = {}

        conversation_type, conversation_id = self._message_conversation_parts(message)
        sender_id = str(sender_data.get("user_id") or "").strip()
        display_name = str(
            sender_data.get("display_name")
            or sender_data.get("card")
            or sender_data.get("nickname")
            or sender_id
            or "unknown"
        ).strip()

        sender_label = display_name
        if sender_id and sender_id != display_name:
            sender_label = f"{display_name} ({sender_id})"

        conversation_label = conversation_type
        if conversation_id:
            conversation_label = f"{conversation_type}:{conversation_id}"

        parts = [
            "Robot message",
            f"conversation={conversation_label}",
        ]
        if trigger_reason:
            parts.append(f"trigger={trigger_reason}")
        parts.append(f"sender={sender_label}")
        mentions_label = self._format_mentions_for_context(
            message.reply_target.metadata.get("mentions"),
            bot_self_ids=self._bot_self_ids_from_message(message),
        )
        if mentions_label:
            parts.append(f"mentions={mentions_label}")
        return f"[{'; '.join(parts)}]"

    def _format_mentions_for_context(
        self,
        raw_mentions: object,
        *,
        bot_self_ids: set[str] | None = None,
    ) -> str:
        if not isinstance(raw_mentions, list):
            return ""

        bot_self_ids = bot_self_ids or set()
        labels: list[str] = []
        for raw_mention in raw_mentions[:8]:
            if not isinstance(raw_mention, dict):
                continue
            mention_id = str(
                raw_mention.get("id") or raw_mention.get("qq") or ""
            ).strip()
            name = str(
                raw_mention.get("name")
                or raw_mention.get("display_name")
                or raw_mention.get("nickname")
                or ""
            ).strip()
            is_self = bool(mention_id and mention_id in bot_self_ids)
            if name and mention_id and name != mention_id:
                label = f"{name} ({mention_id})"
            elif name:
                label = name
            elif mention_id:
                label = mention_id
            else:
                continue
            if is_self:
                label = f"{label} (you)"
            labels.append(label)
        return ", ".join(labels)

    def _write_to_item_terminal(self, item_id: uuid.UUID, command: str) -> bool:
        from app.services import socket_pool_facade

        return socket_pool_facade.write_to_item(str(item_id), command)

    async def _chat_with_item(
        self,
        *,
        session: Session,
        robot: Robot,
        item: Item,
        message: str,
        sender_key: str,
        reply_target: RobotReplyTarget,
        conversation_key: str = "",
        conversation_generation: int = 0,
        reply_requires_awake: bool = False,
        reply_ticket_id: str = "",
    ) -> ChatResponseResult:
        owner = session.get(User, robot.owner_id)
        if owner is None:
            raise RobotServiceError("机器人所属用户不存在", status_code=404)

        try:
            result = await collect_chat_response(
                session=session,
                item_id=str(item.id),
                current_user=owner,
                message=message,
                robot_id=str(robot.id),
                robot_sender_key=sender_key,
                robot_reply_target=reply_target,
                robot_conversation_key=conversation_key,
                robot_conversation_generation=conversation_generation,
                robot_reply_requires_awake=reply_requires_awake,
                reply_ticket_id=reply_ticket_id,
                return_result=True,
            )
            if isinstance(result, ChatResponseResult):
                return result
            return ChatResponseResult(content=str(result or ""))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Item agent is unavailable"
            raise RobotServiceError(detail, status_code=exc.status_code) from exc

    def _assert_robot_supported(self, robot: Robot) -> None:
        provider = (robot.provider or "").lower()
        if provider != "nonebot2":
            raise RobotServiceError(
                f"Unsupported robot provider `{robot.provider}`",
                status_code=400,
            )

        platform_id = normalize_robot_platform_id(robot.platform or robot.protocol)
        try:
            get_robot_platform(platform_id)
            get_robot_runtime_config(robot)
        except ValueError as exc:
            raise RobotServiceError(str(exc), status_code=400) from exc

    def _remember_conversation(
        self,
        robot_id: uuid.UUID,
        sender_key: str,
        item_id: uuid.UUID,
    ) -> None:
        with self._lock:
            self._prune_locked()
            self._conversation_routes[(str(robot_id), sender_key)] = ConversationState(
                item_id=item_id,
                updated_at=self._now(),
            )

    def _get_remembered_item_id(
        self,
        robot_id: uuid.UUID,
        sender_key: str,
    ) -> uuid.UUID | None:
        with self._lock:
            self._prune_locked()
            state = self._conversation_routes.get((str(robot_id), sender_key))
            return state.item_id if state else None

    def _prune_locked(self) -> None:
        now = self._now()
        expired_after = now - CONVERSATION_TTL

        expired_routes = [
            key
            for key, state in self._conversation_routes.items()
            if state.updated_at < expired_after
        ]
        for key in expired_routes:
            self._conversation_routes.pop(key, None)

    def _chunk_text(self, robot: Robot, text: str) -> list[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []

        limit = self._max_message_length(robot, default=DEFAULT_MAX_MESSAGE_LENGTH)
        if len(normalized) <= limit:
            return [normalized]

        chunks: list[str] = []
        remaining = normalized
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        return [chunk for chunk in chunks if chunk]

    def _reply_chunks_for_target(
        self,
        robot: Robot,
        target: RobotReplyTarget,
        text: str,
    ) -> list[str]:
        if is_group_reply_target(target):
            return split_robot_message_for_target(target, text)
        return self._chunk_text(robot, text)

    def _max_message_length(self, robot: Robot, *, default: int) -> int:
        config = robot.config if isinstance(robot.config, dict) else {}
        options = config.get("options") if isinstance(config.get("options"), dict) else {}
        try:
            return max(200, int(options.get("max_message_length") or default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)


robot_service = RobotService()
