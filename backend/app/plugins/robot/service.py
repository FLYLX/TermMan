from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import Item, Robot, RobotItem, User
from app.plugins.robot.conversation_memory import robot_conversation_memory
from app.services.agent.chat_runtime import ChatResponseResult, collect_chat_response

from .contracts import RobotDispatchResponse, RobotInboundMessage, RobotReplyTarget
from .debug_log import preview_text, record_robot_event
from .message_chunks import is_group_reply_target, split_robot_message_for_target
from .platforms import (
    get_robot_platform,
    get_robot_runtime_config,
    normalize_robot_platform_id,
)

logger = logging.getLogger(__name__)

CONVERSATION_TTL = timedelta(hours=6)
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
MENTION_MATCH_MODE_ANY = "any"
DEFAULT_MENTION_MATCH_MODE = MENTION_MATCH_MODE_BOT
ALLOWED_MENTION_MATCH_MODES = frozenset(
    {
        MENTION_MATCH_MODE_BOT,
        MENTION_MATCH_MODE_ANY,
    }
)


@dataclass
class ConversationState:
    item_id: uuid.UUID
    updated_at: datetime


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


class RobotServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RobotService:
    def __init__(self) -> None:
        self._conversation_routes: dict[tuple[str, str], ConversationState] = {}
        self._reply_context_windows: dict[tuple[str, str], datetime] = {}
        self._lock = threading.RLock()
        self._dispatch_queue: queue.Queue[QueuedRobotChatJob] = queue.Queue(
            maxsize=max(1, settings.ROBOT_BACKEND_DISPATCH_QUEUE_SIZE)
        )
        self._dispatch_workers_started = False
        self._dispatch_worker_lock = threading.Lock()

    def dispatch_queue_snapshot(self) -> dict[str, int]:
        return {
            "size": self._dispatch_queue.qsize(),
            "max_size": self._dispatch_queue.maxsize,
            "workers": settings.ROBOT_BACKEND_DISPATCH_WORKERS
            if self._dispatch_workers_started
            else 0,
        }

    def _ensure_dispatch_workers(self) -> None:
        if self._dispatch_workers_started:
            return
        with self._dispatch_worker_lock:
            if self._dispatch_workers_started:
                return
            worker_count = max(1, min(settings.ROBOT_BACKEND_DISPATCH_WORKERS, 8))
            for index in range(worker_count):
                worker = threading.Thread(
                    target=self._dispatch_worker_loop,
                    name=f"termman-backend-robot-dispatch-{index}",
                    daemon=True,
                )
                worker.start()
            self._dispatch_workers_started = True

    def _enqueue_chat_job(self, job: QueuedRobotChatJob) -> bool:
        self._ensure_dispatch_workers()
        try:
            self._dispatch_queue.put_nowait(job)
        except queue.Full:
            return False
        return True

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
                response = asyncio.run(
                    self._chat_with_item(
                        session=session,
                        robot=robot,
                        item=item,
                        message=job.message,
                        sender_key=job.sender_key,
                        reply_target=job.reply_target,
                    )
                )
                self._apply_reply_context_result(
                    robot,
                    job.conversation_key,
                    robot_message_sent=response.robot_message_sent,
                    reply_target=job.reply_target,
                )
                response_text = response.content
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

        response_text = self._visible_agent_response_text(response)
        if not response_text:
            record_robot_event(
                str(job.robot_id),
                direction="backend_to_bridge",
                event="dispatch_completed",
                payload={
                    "item_id": str(job.item_id),
                    "route_key": job.route_key,
                    "robot_message_sent": response.robot_message_sent,
                    "queue": self.dispatch_queue_snapshot(),
                },
            )
            logger.info(
                "[RobotService] Queued agent completed robot=%s item=%s route=%s sent=%s",
                job.robot_id,
                job.item_id,
                job.route_key,
                response.robot_message_sent,
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
                "reply_delivery": "mcp_tool",
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
            from app.services.agent.integrations import fallback_is_delivery_result

            if fallback_is_delivery_result(text):
                return ""
        except Exception:
            pass
        return text

    def _record_and_send_job_error(
        self,
        job: QueuedRobotChatJob,
        message: str,
    ) -> None:
        self._clear_reply_context_window_for_key(
            job.robot_id,
            job.conversation_key,
            reason="dispatch_error",
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
        reply_context_active = self._is_reply_context_active(robot, message)
        conversation_key = self._conversation_key(message)
        text = (message.text or "").strip()
        if not text and not direct_reply_trigger:
            return RobotDispatchResponse(success=True, ignored=True, reason="empty_message")
        if not text and direct_reply_trigger:
            text = "[empty robot wakeup]"
        command = self._parse_robot_command(text)
        self._remember_inbound_conversation_memory(robot, message, conversation_key, text)
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
        if direct_reply_trigger:
            self._remember_reply_context_window(robot, message)
        try:
            resolved_binding, message_text = self._resolve_chat_binding(
                session,
                robot,
                command,
                conversation_key,
                fallback_sender_key=message.sender_key,
            )
            self._remember_conversation(
                robot.id,
                conversation_key,
                resolved_binding.item.id,
            )

            if command.mode == "send":
                success = self._write_to_item_terminal(resolved_binding.item.id, message_text)
                if not success:
                    raise RobotServiceError("终端未运行或后端尚未连接到该终端。")
                response_text = "已发送到终端。"
                self._clear_reply_context_window_for_key(
                    robot.id,
                    conversation_key,
                    reason="terminal_command",
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

            queued_job = QueuedRobotChatJob(
                robot_id=robot.id,
                robot_owner_id=robot.owner_id,
                item_id=resolved_binding.item.id,
                route_key=resolved_binding.route_key,
                message=self._agent_message_with_context(
                    message,
                    message_text,
                    trigger_reason=self._agent_trigger_reason(
                        message,
                        direct_reply_trigger=direct_reply_trigger,
                        reply_context_active=reply_context_active,
                        mention_match_mode=mention_match_mode,
                    ),
                ),
                sender_key=message.sender_key,
                reply_target=message.reply_target.model_copy(deep=True),
                conversation_key=conversation_key,
                direct_reply_trigger=direct_reply_trigger,
                reply_context_active=reply_context_active,
                enqueued_at=self._now(),
            )
            if not self._enqueue_chat_job(queued_job):
                self._clear_reply_context_window_for_key(
                    robot.id,
                    conversation_key,
                    reason="dispatch_queue_full",
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
                    "reply_delivery": "mcp_tool",
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

    def _sender_memory_label(self, message: RobotInboundMessage) -> str:
        sender_data = message.reply_target.metadata.get("sender")
        if isinstance(sender_data, dict):
            sender_id = str(sender_data.get("user_id") or "").strip()
            display_name = str(sender_data.get("display_name") or sender_data.get("card") or sender_data.get("nickname") or sender_id or "").strip()
            if display_name and sender_id and display_name != sender_id:
                return f"{display_name} ({sender_id})"
            return display_name or sender_id
        return message.sender_key

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
            return max(0, int(raw_value if raw_value is not None else settings.ROBOT_REPLY_CONTEXT_WINDOW_SECONDS))
        except (TypeError, ValueError):
            return max(0, settings.ROBOT_REPLY_CONTEXT_WINDOW_SECONDS)

    def _message_directly_addresses_bot(self, message: RobotInboundMessage) -> bool:
        return bool(
            message.reply_target.metadata.get("mentioned_bot")
            or message.reply_target.metadata.get("replied_to_bot")
        )

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

    def _is_reply_context_active(
        self,
        robot: Robot,
        message: RobotInboundMessage,
    ) -> bool:
        now = self._now()
        with self._lock:
            self._prune_reply_context_windows_locked(now)
            expires_at = self._reply_context_windows.get(
                self._reply_context_key(robot, message)
            )
            return expires_at is not None and expires_at > now

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
    ) -> None:
        window_seconds = self._reply_context_window_seconds(robot)
        if window_seconds <= 0:
            return

        now = self._now()
        expires_at = now + timedelta(seconds=window_seconds)
        key = (str(robot.id), conversation_key)
        with self._lock:
            self._prune_reply_context_windows_locked(now)
            self._reply_context_windows[key] = expires_at
        metadata = metadata or {}
        record_robot_event(
            str(robot.id),
            direction="backend",
            event="reply_context_window_refreshed",
            payload={
                "conversation": key[1],
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
    ) -> None:
        if not conversation_key:
            return

        key = (str(robot_id), conversation_key)
        with self._lock:
            removed = self._reply_context_windows.pop(key, None) is not None
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

    def _apply_reply_context_result(
        self,
        robot: Robot,
        conversation_key: str,
        *,
        robot_message_sent: bool,
        reply_target: RobotReplyTarget,
    ) -> None:
        if robot_message_sent:
            self._remember_reply_context_window_for_key(
                robot,
                conversation_key,
                metadata=reply_target.metadata,
            )
            return

        self._clear_reply_context_window_for_key(
            robot.id,
            conversation_key,
            reason="agent_did_not_send_qq_message",
        )

    def _prune_reply_context_windows_locked(self, now: datetime) -> None:
        expired_keys = [
            key for key, expires_at in self._reply_context_windows.items() if expires_at <= now
        ]
        for key in expired_keys:
            self._reply_context_windows.pop(key, None)

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
        if command.mode != "chat" or command.target:
            categories.add(REPLY_MESSAGE_TYPE_COMMAND)
        if direct_reply_trigger or reply_context_active:
            categories.add(REPLY_MESSAGE_TYPE_MENTION)
        elif (
            mention_match_mode == MENTION_MATCH_MODE_ANY
            and self._message_has_mentions(message)
        ):
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

    def _agent_message_with_context(
        self,
        inbound_message: RobotInboundMessage,
        message_text: str,
        *,
        trigger_reason: str = "",
    ) -> str:
        prefix = self._agent_message_context_prefix(
            inbound_message,
            trigger_reason=trigger_reason,
        )
        if not prefix:
            return message_text
        return f"{prefix}\n{message_text}"

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
        if reply_context_active and not direct_reply_trigger:
            return "active_chat_window"
        if (
            mention_match_mode == MENTION_MATCH_MODE_ANY
            and self._message_has_mentions(message)
        ):
            return "mention_any"
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
            message.reply_target.metadata.get("mentions")
        )
        if mentions_label:
            parts.append(f"mentions={mentions_label}")
        return f"[{'; '.join(parts)}]"

    def _format_mentions_for_context(self, raw_mentions: object) -> str:
        if not isinstance(raw_mentions, list):
            return ""

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
            if name and mention_id and name != mention_id:
                labels.append(f"{name} ({mention_id})")
            elif name:
                labels.append(name)
            elif mention_id:
                labels.append(mention_id)
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
