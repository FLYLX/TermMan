from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.db import engine
from app.models import Item, Robot, RobotItem, User
from app.services.agent.chat_runtime import collect_chat_response

from .bridge_client import robot_bridge_client
from .contracts import RobotDispatchResponse, RobotInboundMessage, RobotReplyTarget
from .platforms import (
    get_robot_platform,
    get_robot_runtime_config,
    normalize_robot_platform_id,
)

logger = logging.getLogger(__name__)

CONVERSATION_TTL = timedelta(hours=6)
DEFAULT_MAX_MESSAGE_LENGTH = 1200


@dataclass
class ConversationState:
    item_id: uuid.UUID
    updated_at: datetime


@dataclass
class AudienceState:
    target: RobotReplyTarget
    updated_at: datetime


@dataclass
class ResolvedRobotBinding:
    binding: RobotItem
    item: Item
    route_key: str


class RobotServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RobotService:
    def __init__(self) -> None:
        self._conversation_routes: dict[tuple[str, str], ConversationState] = {}
        self._audiences: dict[tuple[str, str], dict[str, AudienceState]] = {}
        self._lock = threading.RLock()

    async def handle_inbound_message(
        self,
        session: Session,
        robot: Robot,
        message: RobotInboundMessage,
    ) -> RobotDispatchResponse:
        self._assert_robot_supported(robot)
        if not robot.is_enabled:
            return RobotDispatchResponse(success=True, ignored=True, reason="robot_disabled")

        text = (message.text or "").strip()
        if not text:
            return RobotDispatchResponse(success=True, ignored=True, reason="empty_message")

        try:
            resolved_binding, message_text = self._resolve_chat_binding(
                session,
                robot,
                message,
            )
            self._remember_conversation(robot.id, message.sender_key, resolved_binding.item.id)
            self._register_audience(
                robot.id,
                resolved_binding.item.id,
                message.sender_key,
                message.reply_target.model_copy(deep=True),
            )

            response_text = await self._chat_with_item(
                session=session,
                robot=robot,
                item=resolved_binding.item,
                message=message_text,
            )
            return RobotDispatchResponse(
                success=True,
                ignored=False,
                item_id=str(resolved_binding.item.id),
                route_key=resolved_binding.route_key,
                reply_chunks=self._chunk_text(robot, response_text),
            )
        except RobotServiceError as exc:
            return RobotDispatchResponse(
                success=False,
                ignored=False,
                error=exc.message,
                reply_chunks=self._chunk_text(robot, exc.message),
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Robot dispatch failed"
            return RobotDispatchResponse(
                success=False,
                ignored=False,
                error=detail,
                reply_chunks=self._chunk_text(robot, detail),
            )
        except Exception as exc:
            logger.exception(
                "[RobotService] Unexpected inbound message error for robot %s",
                robot.id,
            )
            fallback = "机器人处理失败"
            return RobotDispatchResponse(
                success=False,
                ignored=False,
                error=str(exc),
                reply_chunks=self._chunk_text(robot, fallback),
            )

    def dispatch_filtered_output(
        self,
        item_id: str,
        filtered_output: str,
        *,
        item_title: str | None = None,
    ) -> None:
        text = (filtered_output or "").strip()
        if not text:
            return

        try:
            item_uuid = uuid.UUID(str(item_id))
        except ValueError:
            logger.warning("[RobotService] Invalid item id for output dispatch: %s", item_id)
            return

        with Session(engine) as session:
            item = session.get(Item, item_uuid)
            if item is None:
                return

            title = item_title or item.title or "Item"
            bindings = session.exec(
                select(RobotItem).where(
                    RobotItem.item_id == item_uuid,
                    RobotItem.receive_filtered_output == True,  # noqa: E712
                )
            ).all()

            for binding in bindings:
                robot = session.get(Robot, binding.robot_id)
                if robot is None or not robot.is_enabled:
                    continue

                try:
                    self._assert_robot_supported(robot)
                except RobotServiceError:
                    continue

                targets = self._reserve_audience_targets(robot.id, item_uuid)
                if not targets:
                    continue

                output_text = f"[{title}]\n{text}"
                for target in targets:
                    self._safe_send_via_bridge(robot, target, output_text)

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
        message: RobotInboundMessage,
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

        explicit_route_key, message_text = self._extract_route_key(message.text)
        if explicit_route_key:
            for resolved in bindings:
                if resolved.route_key == explicit_route_key:
                    if not message_text:
                        raise RobotServiceError("请在路由别名后补充要发给 agent 的内容")
                    return resolved, message_text
            raise RobotServiceError(f"没有找到路由 `{explicit_route_key}` 对应的终端")

        remembered_item_id = self._get_remembered_item_id(robot.id, message.sender_key)
        if remembered_item_id:
            for resolved in bindings:
                if resolved.item.id == remembered_item_id:
                    return resolved, (message.text or "").strip()

        default_bindings = [binding for binding in bindings if binding.binding.is_default_target]
        if len(default_bindings) == 1:
            return default_bindings[0], (message.text or "").strip()

        if len(bindings) == 1:
            return bindings[0], (message.text or "").strip()

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

    async def _chat_with_item(
        self,
        *,
        session: Session,
        robot: Robot,
        item: Item,
        message: str,
    ) -> str:
        owner = session.get(User, robot.owner_id)
        if owner is None:
            raise RobotServiceError("机器人所属用户不存在", status_code=404)

        try:
            return await collect_chat_response(
                session=session,
                item_id=str(item.id),
                current_user=owner,
                message=message,
            )
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

    def _register_audience(
        self,
        robot_id: uuid.UUID,
        item_id: uuid.UUID,
        sender_key: str,
        target: RobotReplyTarget,
    ) -> None:
        with self._lock:
            self._prune_locked()
            audience_key = (str(robot_id), str(item_id))
            audience = self._audiences.setdefault(audience_key, {})
            audience[sender_key] = AudienceState(target=target, updated_at=self._now())

    def _reserve_audience_targets(
        self,
        robot_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> list[RobotReplyTarget]:
        with self._lock:
            self._prune_locked()
            audience = self._audiences.get((str(robot_id), str(item_id)), {})
            unique_targets: dict[tuple[str, str, str | None], RobotReplyTarget] = {}

            for state in audience.values():
                target = state.target.model_copy(deep=True)
                if target.target_type in {"c2c", "group"}:
                    msg_id = str(target.metadata.get("msg_id") or "").strip()
                    if not msg_id:
                        continue
                    next_seq = max(int(target.metadata.get("msg_seq") or 0) + 1, 1)
                    target.metadata["msg_id"] = msg_id
                    target.metadata["msg_seq"] = next_seq
                    state.target.metadata["msg_id"] = msg_id
                    state.target.metadata["msg_seq"] = next_seq

                key = (
                    target.target_type,
                    target.target_id,
                    str(target.metadata.get("msg_id") or "") or None,
                )
                unique_targets[key] = target

            return list(unique_targets.values())

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

        expired_audience_keys: list[tuple[str, str]] = []
        for key, audience in self._audiences.items():
            expired_members = [
                sender_key
                for sender_key, state in audience.items()
                if state.updated_at < expired_after
            ]
            for sender_key in expired_members:
                audience.pop(sender_key, None)
            if not audience:
                expired_audience_keys.append(key)

        for key in expired_audience_keys:
            self._audiences.pop(key, None)

    def _send_via_bridge(self, robot: Robot, target: RobotReplyTarget, text: str) -> None:
        for chunk in self._chunk_text(robot, text):
            robot_bridge_client.send_message(str(robot.id), target, chunk)
            if target.target_type in {"c2c", "group"}:
                current_seq = max(int(target.metadata.get("msg_seq") or 0), 1)
                target.metadata["msg_seq"] = current_seq + 1

    def _safe_send_via_bridge(self, robot: Robot, target: RobotReplyTarget, text: str) -> None:
        try:
            self._send_via_bridge(robot, target, text)
        except Exception as exc:
            logger.warning(
                "[RobotService] Failed to send bridge message for robot %s: %s",
                robot.id,
                exc,
            )

    def _chunk_text(self, robot: Robot, text: str) -> list[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []

        config = robot.config if isinstance(robot.config, dict) else {}
        options = config.get("options") if isinstance(config.get("options"), dict) else {}
        limit = int(options.get("max_message_length") or DEFAULT_MAX_MESSAGE_LENGTH)
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

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)


robot_service = RobotService()
