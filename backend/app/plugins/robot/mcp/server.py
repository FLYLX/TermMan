from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import uuid
from datetime import datetime
from typing import Any

from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.internal_trace import (
    compact_robot_visible_message_text,
    is_robot_internal_trace_text,
    sanitize_robot_visible_text,
)
from app.plugins.robot.mcp.context import get_robot_mcp_context
from app.plugins.robot.memory_scope import (
    memory_conversation_key as scoped_memory_conversation_key,
    memory_scope_for_content,
    memory_scope_rank as scoped_memory_scope_rank,
    speaker_global_key_from_context,
)
from app.plugins.robot.message_chunks import is_group_reply_target
from app.plugins.robot.reply_intent import is_no_reply_intent

logger = logging.getLogger(__name__)

MAX_GROUP_SINGLE_TEXT_CHARS = 36
DEFAULT_MEMORY_RECENT_LINES = 8
ACTIVE_CONTEXT_MEMORY_MAX_LINES = 12
GENERAL_MEMORY_MAX_LINES = 500
DEFAULT_LONG_TERM_MEMORY_RESULTS = 5
MAX_LONG_TERM_MEMORY_RESULTS = 8
LONG_TERM_MEMORY_CANDIDATE_MULTIPLIER = 6
LONG_TERM_MEMORY_TYPES = {"fact", "preference", "task", "error", "context"}
LONG_TERM_MEMORY_TYPE_ORDER = ("preference", "fact", "context", "task", "error")
LONG_TERM_MEMORY_TYPE_RANK = {
    "preference": 5,
    "fact": 4,
    "context": 3,
    "task": 2,
    "error": 2,
}


class RobotMCPServer:
    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        self.register_tool(
            name="send_message",
            description=(
                "Send a concise message through the TermMan QQ connector. "
                "In an incoming QQ-triggered agent turn, calling this tool with only "
                "text sends to the current QQ conversation that triggered the turn. "
                "Do not use reply_to, conversation, broadcast, target_type, or "
                "target_id in that incoming QQ-triggered context; cross-conversation "
                "sends are blocked there to prevent replying to the wrong group. "
                "In backend chat, use reply_to only when intentionally choosing a "
                "different QQ conversation visible in context. Use target_type and "
                "target_id only when the user explicitly provided a QQ group number "
                "or QQ number outside the visible context. If multiple robots are "
                "available, provide robot_id."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "Single QQ message text. Use this for one-message replies. "
                            "Do not put blank lines, paragraph breaks, or multiple "
                            "information blocks inside this field. For QQ groups, "
                            "keep this within 36 characters; use messages for more."
                        ),
                    },
                    "messages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                        "description": (
                            "Optional ordered QQ messages for human-like "
                            "multi-message replies. Use only when a normal chat "
                            "reply would naturally follow up or add one more "
                            "thought. The LLM decides each complete message; the "
                            "backend sends each array item as one QQ message in "
                            "order. Do not split into tiny fragments, and do not "
                            "use this for long logs or summaries. Do not put blank "
                            "lines or paragraph breaks inside any one array item."
                        ),
                    },
                    "target_type": {
                        "type": "string",
                        "enum": ["group", "private"],
                        "description": (
                            "Optional in QQ-triggered robot context. Required in "
                            "backend chat. Use 'group' for QQ group messages and "
                            "'private' for QQ private messages."
                        ),
                    },
                    "target_id": {
                        "type": "string",
                        "description": (
                            "Optional in QQ-triggered robot context. Required in "
                            "backend chat. QQ group number for group messages, or QQ "
                            "number for private messages."
                        ),
                    },
                    "conversation": {
                        "type": "string",
                        "description": (
                            "Optional conversation reference from context, for "
                            "example 'group:123456' or 'private:654321'. Use this "
                            "when choosing a conversation from prior QQ context."
                        ),
                    },
                    "reply_to": {
                        "type": "string",
                        "description": (
                            "Optional natural reference to the QQ conversation from "
                            "context, such as the sender name, group/private label, "
                            "or conversation shown in prior robot messages. The "
                            "backend resolves it against the context target index."
                        ),
                    },
                    "robot_id": {
                        "type": "string",
                        "description": (
                            "Optional robot UUID. Omit only when there is an active "
                            "QQ robot context or exactly one accessible enabled robot."
                        ),
                    },
                    "broadcast": {
                        "type": "boolean",
                        "description": (
                            "When true, send the same message to every QQ "
                            "conversation visible in the current chat context. Use "
                            "for severe terminal alerts only."
                        ),
                    },
                },
            },
            handler=self._send_message,
            skip_memory=True,
        )
        self.register_tool(
            name="read_conversation_memory",
            description=(
                "Read or search the conversation-local QQ .log memory for the "
                "TermMan robot. In an incoming QQ-triggered agent turn, call this "
                "tool with no target arguments to read the current QQ "
                "conversation that woke the agent only when the user explicitly "
                "asks about previous QQ context or the current message cannot be "
                "answered without earlier chat. Do not call this tool just to "
                "decide whether to reply or to verify whether the current reply "
                "was sent. In backend chat, use conversation or reply_to only for "
                "a QQ conversation visible in context, or provide "
                "target_type/target_id plus robot_id when the user explicitly "
                "supplied them."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "conversation": {
                        "type": "string",
                        "description": (
                            "Optional conversation key such as 'group:123456' or "
                            "'private:654321'. In active QQ context this must "
                            "match the current conversation."
                        ),
                    },
                    "reply_to": {
                        "type": "string",
                        "description": (
                            "Optional natural reference resolved against visible "
                            "QQ context in backend chat."
                        ),
                    },
                    "target_type": {
                        "type": "string",
                        "enum": ["group", "private"],
                        "description": "Optional explicit QQ target type.",
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Optional explicit QQ group number or QQ number.",
                    },
                    "robot_id": {
                        "type": "string",
                        "description": "Optional robot UUID when no active QQ context exists.",
                    },
                    "lines": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "description": (
                            "Maximum recent or matching log lines to return. "
                            "Default is 8; active QQ-triggered context is "
                            "capped to the latest 12 lines."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional case-insensitive text filter.",
                    },
                },
            },
            handler=self._read_conversation_memory,
            skip_memory=True,
        )
        self.register_tool(
            name="recall_memory",
            description=(
                "Search TermMan long-term memory for stable facts, user "
                "preferences, tasks, errors, and reusable context. This is "
                "not raw QQ .log history. In an incoming QQ-triggered turn, "
                "use this when the current message asks what the bot remembers, "
                "refers to a known preference/person/fact, or needs durable "
                "context. Omit target arguments; results are scoped to the "
                "current TermMan item and prefer the current QQ conversation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query built from the current user message.",
                    },
                    "n_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_LONG_TERM_MEMORY_RESULTS,
                        "description": "Maximum memories to return. Default is 5.",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": sorted(LONG_TERM_MEMORY_TYPES),
                        "description": "Optional memory type filter.",
                    },
                },
                "required": ["query"],
            },
            handler=self._recall_memory,
            skip_memory=True,
        )
        self.register_tool(
            name="save_memory",
            description=(
                "Save concise, durable information from the current QQ chat into "
                "TermMan long-term memory for the bound terminal item. Use this "
                "when the live QQ message contains an explicit remember request, "
                "stable names/nicknames, bot identity/name rules, durable user "
                "preferences, relationships, ongoing tasks, reusable facts, or "
                "recurring group context. Do not save trivial chat, images, short "
                "reactions, temporary chatter, raw logs, or sensitive secrets."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Concise normalized memory text to save.",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": sorted(LONG_TERM_MEMORY_TYPES),
                        "description": "Memory type. Default is fact.",
                    },
                    "ttl_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3650,
                        "description": "Optional retention days; defaults by memory type.",
                    },
                },
                "required": ["content"],
            },
            handler=self._save_memory,
            skip_memory=True,
        )
        self.register_tool(
            name="sleep_conversation",
            description=(
                "Put the current QQ conversation to sleep. Use this only in an "
                "incoming QQ-triggered context when the current sender asks the "
                "bot to sleep, stop replying, be quiet, or not answer this chat, "
                "or when a `trigger=active_chat_window` message is ordinary "
                "group chatter not addressed to the bot. "
                "It closes the robot controller for this group/private chat until "
                "someone wakes the bot again by mentioning or replying to it."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=self._sleep_conversation,
            skip_memory=True,
        )

    def _normalize_target_type(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"group", "qq_group"}:
            return "group"
        if raw in {"private", "friend", "user", "direct", "c2c"}:
            return "private"
        return ""

    def _parse_conversation_target(self, value: Any) -> tuple[str, str]:
        raw = str(value or "").strip()
        if not raw or ":" not in raw:
            return "", ""
        target_type, target_id = raw.split(":", 1)
        return self._normalize_target_type(target_type), target_id.strip()

    def _context_reference(self, args: dict) -> str:
        return str(
            args.get("reply_to")
            or args.get("recipient")
            or args.get("conversation")
            or ""
        ).strip()

    def _build_explicit_target(self, args: dict) -> RobotReplyTarget | None:
        target_type = self._normalize_target_type(
            args.get("target_type") or args.get("mcp_target_type")
        )
        target_id = str(args.get("target_id") or args.get("mcp_target_id") or "").strip()
        if not target_type and not target_id:
            return None
        if not target_type:
            raise ValueError("target_type is required when target_id is provided")
        if not target_id:
            raise ValueError("target_id is required when target_type is provided")
        return RobotReplyTarget(
            target_type=target_type,
            target_id=target_id,
            metadata={"manual_target": True, "mcp_explicit_target": True},
        )

    def _build_conversation_target(self, args: dict) -> RobotReplyTarget | None:
        target_type, target_id = self._parse_conversation_target(args.get("conversation"))
        if target_type not in {"group", "private"} or not target_id:
            return None
        return RobotReplyTarget(
            target_type=target_type,
            target_id=target_id,
            metadata={"manual_target": True, "mcp_explicit_conversation": True},
        )

    def _context_targets(self, args: dict) -> list[dict[str, str]]:
        raw_targets = args.get("_robot_known_targets")
        if not isinstance(raw_targets, list):
            return []

        targets: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_target in raw_targets:
            if not isinstance(raw_target, dict):
                continue
            target_type = self._normalize_target_type(raw_target.get("target_type"))
            target_id = str(raw_target.get("target_id") or "").strip()
            if target_type not in {"group", "private"} or not target_id:
                continue
            key = f"{target_type}:{target_id}"
            if key in seen:
                continue
            seen.add(key)
            conversation = str(raw_target.get("conversation") or key).strip() or key
            targets.append(
                {
                    "conversation": conversation,
                    "target_type": target_type,
                    "target_id": target_id,
                    "sender": str(raw_target.get("sender") or "").strip(),
                    "robot_id": str(raw_target.get("robot_id") or "").strip(),
                }
            )
        return targets

    def _context_target_from_active_context(
        self,
        context: Any,
    ) -> dict[str, str] | None:
        if context is None:
            return None
        target = context.reply_target
        conversation_data = target.metadata.get("conversation")
        if isinstance(conversation_data, dict):
            target_type = self._normalize_target_type(
                conversation_data.get("target_type")
                or conversation_data.get("type")
                or conversation_data.get("conversation_type")
            )
            target_id = str(
                conversation_data.get("target_id")
                or conversation_data.get("id")
                or conversation_data.get("conversation_id")
                or ""
            ).strip()
            if target_type in {"group", "private"} and target_id:
                return {
                    "conversation": f"{target_type}:{target_id}",
                    "target_type": target_type,
                    "target_id": target_id,
                    "sender": "",
                    "robot_id": context.robot_id,
                }

        target_type = self._normalize_target_type(target.target_type)
        target_id = str(target.target_id or "").strip()
        target_data = target.metadata.get("target")
        if isinstance(target_data, dict):
            if bool(target_data.get("private")):
                target_type = "private"
            elif bool(target_data.get("channel")):
                return None
            target_id = str(
                target_data.get("group_id")
                or target_data.get("user_id")
                or target_data.get("parent_id")
                or target_data.get("id")
                or target_id
            ).strip()
        if target_type not in {"group", "private"} or not target_id:
            return None
        return {
            "conversation": f"{target_type}:{target_id}",
            "target_type": target_type,
            "target_id": target_id,
            "sender": "",
            "robot_id": context.robot_id,
        }

    def _broadcast_context_targets(
        self,
        *,
        args: dict,
        text: str,
        context: Any,
    ) -> list[dict[str, str]]:
        targets = self._context_targets(args)
        active_target = self._context_target_from_active_context(context)
        if active_target is not None:
            active_key = f"{active_target['target_type']}:{active_target['target_id']}"
            if all(
                f"{target['target_type']}:{target['target_id']}" != active_key
                for target in targets
            ):
                targets.insert(0, active_target)

        if not targets:
            raise ValueError(
                "broadcast requires at least one visible QQ conversation target"
            )

        from app.plugins.robot.bridge_client import robot_bridge_client

        sent: list[dict[str, str]] = []
        delivered: list[tuple[str, RobotReplyTarget]] = []
        for target_data in targets:
            target = RobotReplyTarget(
                target_type=target_data["target_type"],
                target_id=target_data["target_id"],
                metadata={
                    "manual_target": True,
                    "mcp_context_target": True,
                    "mcp_context_broadcast": True,
                },
            )
            fallback_robot_id = target_data.get("robot_id", "")
            if not fallback_robot_id and context is not None:
                fallback_robot_id = context.robot_id
            robot_id = self._get_accessible_robot_id(
                args,
                fallback_robot_id=fallback_robot_id,
            )
            self._record_tool_send_event(
                robot_id=robot_id,
                target=target,
                text=text,
                mode="context_broadcast",
                args=args,
            )
            robot_bridge_client.send_message(robot_id, target, text)
            delivered.append((robot_id, target))
            sent.append(
                {
                    "robot_id": robot_id,
                    "conversation": target_data["conversation"],
                    "target_type": target.target_type,
                    "target_id": target.target_id,
                }
            )
        for robot_id, target in delivered:
            self._remember_sent_message(robot_id, target, text)
        return sent

    def _target_match_score(self, target: dict[str, str], reference: str) -> int:
        normalized_reference = reference.strip().casefold()
        if not normalized_reference:
            return 0

        conversation = target.get("conversation", "")
        target_type = target.get("target_type", "")
        target_id = target.get("target_id", "")
        sender = target.get("sender", "")
        exact_candidates = {
            conversation,
            f"{target_type}:{target_id}",
            target_id,
            sender,
        }
        if normalized_reference in {candidate.casefold() for candidate in exact_candidates if candidate}:
            return 100

        partial_candidates = [
            conversation,
            f"{target_type}:{target_id}",
            f"{target_type} {target_id}",
            target_id,
            sender,
            target_type,
        ]
        return sum(
            1
            for candidate in partial_candidates
            if candidate
            and (
                normalized_reference in candidate.casefold()
                or candidate.casefold() in normalized_reference
            )
        )

    def _resolve_context_target(self, args: dict) -> tuple[RobotReplyTarget | None, str]:
        targets = self._context_targets(args)
        if not targets:
            return None, ""

        reference = self._context_reference(args)
        if not reference and len(targets) == 1:
            target_data = targets[0]
            return (
                RobotReplyTarget(
                    target_type=target_data["target_type"],
                    target_id=target_data["target_id"],
                    metadata={
                        "manual_target": True,
                        "mcp_context_target": True,
                    },
                ),
                target_data.get("robot_id", ""),
            )

        if reference:
            parsed_type, parsed_id = self._parse_conversation_target(reference)
            if parsed_type and parsed_id:
                reference = f"{parsed_type}:{parsed_id}"

            scored = [
                (self._target_match_score(target, reference), target)
                for target in targets
            ]
            matches = [target for score, target in scored if score > 0]
            if len(matches) == 1:
                target_data = matches[0]
                return (
                    RobotReplyTarget(
                        target_type=target_data["target_type"],
                        target_id=target_data["target_id"],
                        metadata={
                            "manual_target": True,
                            "mcp_context_target": True,
                            "mcp_context_reference": reference,
                        },
                    ),
                    target_data.get("robot_id", ""),
                )
            if len(matches) > 1:
                choices = ", ".join(
                    f"{target['conversation']} sender={target.get('sender') or '-'}"
                    for target in matches[:5]
                )
                raise ValueError(
                    "The reply target is ambiguous in context. Choose one of: "
                    f"{choices}"
                )
            choices = ", ".join(
                f"{target['conversation']} sender={target.get('sender') or '-'}"
                for target in targets[:5]
            )
            raise ValueError(
                "No QQ conversation matched reply_to/conversation "
                f"`{reference}`. Choose one of: {choices}"
            )

        if len(targets) > 1:
            choices = ", ".join(
                f"{target['conversation']} sender={target.get('sender') or '-'}"
                for target in targets[:5]
            )
            raise ValueError(
                "Multiple QQ conversations are available in context. Set reply_to "
                f"to one of: {choices}"
            )
        return None, ""

    def _same_target(self, left: RobotReplyTarget, right: dict[str, str]) -> bool:
        left_type = self._normalize_target_type(left.target_type)
        left_id = str(left.target_id or "").strip()
        left_data = left.metadata.get("conversation")
        if isinstance(left_data, dict):
            left_type = self._normalize_target_type(
                left_data.get("target_type")
                or left_data.get("type")
                or left_data.get("conversation_type")
                or left_type
            )
            left_id = str(
                left_data.get("target_id")
                or left_data.get("id")
                or left_data.get("conversation_id")
                or left_id
            ).strip()
        return left_type == right.get("target_type") and left_id == right.get("target_id")

    def _reference_matches_active_target(
        self,
        reference: str,
        active_target: dict[str, str],
    ) -> bool:
        normalized = reference.strip().casefold()
        if not normalized:
            return True
        candidates = {
            active_target.get("conversation", ""),
            f"{active_target.get('target_type', '')}:{active_target.get('target_id', '')}",
            active_target.get("target_id", ""),
        }
        return normalized in {candidate.casefold() for candidate in candidates if candidate}

    def _active_context_target_override_error(
        self,
        *,
        context: Any,
        explicit_target: RobotReplyTarget | None,
        broadcast: bool,
        context_reference: str,
    ) -> str:
        if context is None:
            return ""

        active_target = self._context_target_from_active_context(context)
        active_label = (
            active_target["conversation"] if active_target is not None else "current"
        )
        error = (
            "Error: active QQ-triggered context is locked to "
            f"{active_label}. Omit reply_to/conversation/broadcast/target_type/"
            "target_id to send to the current QQ conversation. Cross-conversation "
            "sends must be initiated from backend chat, not from an incoming QQ "
            "message turn."
        )

        if broadcast:
            return error
        if explicit_target is not None:
            if active_target is not None and self._same_target(
                explicit_target,
                active_target,
            ):
                return ""
            return error
        if context_reference and (
            active_target is None
            or not self._reference_matches_active_target(context_reference, active_target)
        ):
            return error
        return ""

    def _active_context_delivery_error(self, context: Any) -> str:
        if context is None or not bool(getattr(context, "reply_requires_awake", False)):
            return ""
        try:
            conversation_generation = int(
                getattr(context, "conversation_generation", 0) or 0
            )
        except (TypeError, ValueError):
            conversation_generation = 0

        from app.plugins.robot.service import robot_service

        if robot_service.conversation_controller_allows_reply(
            getattr(context, "robot_id", ""),
            getattr(context, "conversation_key", ""),
            conversation_generation,
            requires_awake=True,
        ):
            return ""
        return "Message not sent: current QQ conversation is sleeping or superseded."

    def _get_accessible_robot_id(
        self,
        args: dict,
        *,
        fallback_robot_id: str = "",
    ) -> str:
        explicit_robot_id = str(args.get("robot_id") or "").strip()
        if explicit_robot_id:
            return self._assert_robot_access(explicit_robot_id, args)
        if fallback_robot_id:
            return fallback_robot_id
        return self._single_accessible_robot_id(args)

    def _assert_robot_access(self, robot_id: str, args: dict) -> str:
        try:
            parsed_robot_id = uuid.UUID(robot_id)
        except ValueError as exc:
            raise ValueError("robot_id must be a valid UUID") from exc

        from sqlmodel import Session

        from app.core.db import engine
        from app.models import Robot

        with Session(engine) as session:
            robot = session.get(Robot, parsed_robot_id)
            if robot is None:
                raise ValueError(f"Robot not found: {robot_id}")
            if not robot.is_enabled:
                raise ValueError(f"Robot is disabled: {robot_id}")
            self._assert_user_can_use_robot(robot, args)
        return str(parsed_robot_id)

    def _single_accessible_robot_id(self, args: dict) -> str:
        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import Robot

        user_id = str(args.get("_termman_user_id") or "").strip()
        is_superuser = bool(args.get("_termman_is_superuser"))
        if not user_id and not is_superuser:
            raise ValueError(
                "robot_id is required outside an active robot conversation context"
            )

        with Session(engine) as session:
            statement = select(Robot).where(Robot.is_enabled == True)  # noqa: E712
            if not is_superuser:
                statement = statement.where(Robot.owner_id == uuid.UUID(user_id))
            robots = list(session.exec(statement).all())

        if len(robots) == 1:
            return str(robots[0].id)
        if not robots:
            raise ValueError("No enabled QQ robot is available for this user")

        choices = ", ".join(f"{robot.name} ({robot.id})" for robot in robots[:5])
        raise ValueError(
            "Multiple enabled QQ robots are available; provide robot_id. "
            f"Available robots: {choices}"
        )

    def _assert_user_can_use_robot(self, robot: Any, args: dict) -> None:
        if bool(args.get("_termman_is_superuser")):
            return
        user_id = str(args.get("_termman_user_id") or "").strip()
        if not user_id:
            raise ValueError("Not authorized to use this robot")
        if str(robot.owner_id) != user_id:
            raise ValueError("Not authorized to use this robot")

    def _record_tool_send_event(
        self,
        *,
        robot_id: str,
        target: RobotReplyTarget,
        text: str,
        mode: str,
        args: dict,
        status: str = "ok",
        error: str = "",
    ) -> None:
        from app.plugins.robot.debug_log import preview_text, record_robot_event

        payload = {
            "mode": mode,
            "target_type": target.target_type,
            "target_id": target.target_id,
            "reply_to": str(args.get("reply_to") or "").strip() or None,
            "conversation": str(args.get("conversation") or "").strip() or None,
            "has_context_token": bool(str(args.get("_robot_context_token") or "").strip()),
            "context_target_count": len(self._context_targets(args)),
        }
        if error:
            payload["error"] = error
        record_robot_event(
            robot_id,
            direction="agent_to_mcp",
            event="robot_tool_send_requested",
            status=status,
            message=preview_text(text),
            payload=payload,
        )

    def _remember_sent_message(
        self,
        robot_id: str,
        target: RobotReplyTarget,
        text: str,
    ) -> None:
        try:
            from app.plugins.robot.conversation_memory import (
                conversation_key_from_reply_target,
                robot_conversation_memory,
            )

            robot_conversation_memory.append_assistant_message(
                robot_id,
                conversation_key_from_reply_target(target),
                text,
            )
        except Exception:
            logger.exception("[RobotMCPServer] Failed to write sent QQ memory")

    def _remember_sent_messages(
        self,
        robot_id: str,
        target: RobotReplyTarget,
        messages: list[str],
    ) -> None:
        for message in messages:
            self._remember_sent_message(robot_id, target, message)

    @staticmethod
    def _send_messages(
        bridge_client: Any,
        robot_id: str,
        target: RobotReplyTarget,
        messages: list[str],
    ) -> None:
        for message in messages:
            bridge_client.send_message(robot_id, target, message)

    @staticmethod
    def _raw_message_texts(args: dict) -> list[str]:
        raw_messages = args.get("messages")
        if isinstance(raw_messages, list):
            return [str(value or "") for value in raw_messages]
        raw_text = args.get("text")
        if raw_text is None:
            return []
        return [str(raw_text)]

    @staticmethod
    def _sanitize_outgoing_messages(raw_messages: list[str]) -> list[str]:
        messages: list[str] = []
        for raw_message in raw_messages[:5]:
            text = compact_robot_visible_message_text(
                sanitize_robot_visible_text(str(raw_message or ""))
            )
            if text and not is_no_reply_intent(text) and not is_robot_internal_trace_text(text):
                messages.append(text)
        return messages

    @staticmethod
    def _uses_messages_array(args: dict) -> bool:
        return isinstance(args.get("messages"), list)

    @staticmethod
    def _single_text_too_long_for_group(
        args: dict,
        target: RobotReplyTarget,
        messages: list[str],
    ) -> bool:
        if RobotMCPServer._uses_messages_array(args):
            return False
        if len(messages) != 1 or not is_group_reply_target(target):
            return False
        return len(messages[0]) > MAX_GROUP_SINGLE_TEXT_CHARS

    @staticmethod
    def _group_single_text_too_long_error(text: str) -> str:
        return (
            "Error: QQ group reply is too long for a single `text` message. "
            "Use `messages` with 2-3 complete natural chat messages instead. "
            "Do not split into tiny fragments. Single group text limit: "
            f"{MAX_GROUP_SINGLE_TEXT_CHARS} chars. Current text length: "
            f"{len(text)} chars."
        )

    @staticmethod
    def _memory_line_limit(
        args: dict,
        *,
        max_lines: int = GENERAL_MEMORY_MAX_LINES,
    ) -> int:
        raw_value = (
            args.get("lines")
            or args.get("limit")
            or DEFAULT_MEMORY_RECENT_LINES
        )
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = DEFAULT_MEMORY_RECENT_LINES
        return max(1, min(max_lines, value))

    @staticmethod
    def _filter_memory_lines(content: str, query: str, *, lines: int) -> str:
        normalized_query = query.casefold()
        matches = [
            line
            for line in content.splitlines()
            if normalized_query in line.casefold()
        ]
        return sanitize_robot_visible_text("\n".join(matches[-lines:]))

    def _active_context_memory_target_error(
        self,
        active_target: dict[str, str] | None,
    ) -> str:
        active_label = (
            active_target["conversation"] if active_target is not None else "current"
        )
        return (
            "Error: active QQ-triggered context is locked to "
            f"{active_label}. Omit reply_to/conversation/target_type/target_id "
            "to read the current QQ conversation memory. Cross-conversation "
            "memory reads must be initiated from backend chat, not from an "
            "incoming QQ message turn."
        )

    def _sleep_conversation(self, args: dict) -> list[dict[str, str]]:
        context_token = str(args.get("_robot_context_token") or "").strip()
        context = get_robot_mcp_context(context_token)
        if context is None:
            return [
                {
                    "type": "text",
                    "text": "Error: sleep_conversation requires an active QQ context.",
                }
            ]
        active_target = self._context_target_from_active_context(context)
        conversation_key = str(getattr(context, "conversation_key", "") or "").strip()
        if not conversation_key and active_target is not None:
            conversation_key = active_target["conversation"]
        if not conversation_key:
            return [
                {
                    "type": "text",
                    "text": "Error: current QQ conversation is unavailable.",
                }
            ]

        from app.plugins.robot.service import robot_service

        robot_service.sleep_conversation_controller(
            getattr(context, "robot_id", ""),
            conversation_key,
            reason="mcp_sleep_conversation",
        )
        return [
            {
                "type": "text",
                "text": "No QQ message sent: current conversation is sleeping.",
            }
        ]
    def _long_term_memory_limit(self, args: dict) -> int:
        raw_value = args.get("n_results") or args.get("limit") or DEFAULT_LONG_TERM_MEMORY_RESULTS
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = DEFAULT_LONG_TERM_MEMORY_RESULTS
        return max(1, min(MAX_LONG_TERM_MEMORY_RESULTS, value))

    @staticmethod
    def _memory_distance(memory: dict[str, Any]) -> float:
        try:
            return float(memory.get("distance"))
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _memory_similarity_label(memory: dict[str, Any]) -> str:
        distance = memory.get("distance")
        try:
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
        except (TypeError, ValueError):
            return ""
        return f", score {similarity:.2f}"

    @staticmethod
    def _memory_metadata(memory: dict[str, Any]) -> dict[str, Any]:
        metadata = memory.get("metadata") or {}
        return metadata if isinstance(metadata, dict) else {}

    @classmethod
    def _memory_type(cls, memory: dict[str, Any]) -> str:
        return str(cls._memory_metadata(memory).get("memory_type") or "fact")

    @staticmethod
    def _parse_memory_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def _memory_timestamp(cls, memory: dict[str, Any]) -> float:
        metadata = cls._memory_metadata(memory)
        parsed = cls._parse_memory_datetime(
            metadata.get("updated_at") or metadata.get("created_at")
        )
        if parsed is None:
            return 0.0
        try:
            return parsed.timestamp()
        except OSError:
            return 0.0

    @classmethod
    def _memory_expired(cls, memory: dict[str, Any]) -> bool:
        parsed = cls._parse_memory_datetime(
            cls._memory_metadata(memory).get("expires_at")
        )
        if parsed is None:
            return False
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return parsed < now

    @classmethod
    def _memory_inactive(cls, memory: dict[str, Any]) -> bool:
        metadata = cls._memory_metadata(memory)
        memory_type = str(metadata.get("memory_type") or "")
        status = str(metadata.get("status") or "").lower()
        return (
            (memory_type == "task" and status == "completed")
            or (memory_type == "error" and status == "resolved")
        )

    @staticmethod
    def _memory_tokens(value: str) -> set[str]:
        return {
            token.casefold()
            for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_./:-]+", value or "")
            if len(token.strip()) > 1
        }

    @classmethod
    def _memory_query_score(cls, memory: dict[str, Any], query: str) -> float:
        query_tokens = cls._memory_tokens(query)
        if not query_tokens:
            return 0.0
        content = str(memory.get("content") or "")
        content_folded = content.casefold()
        score = 0.0
        normalized_query = query.casefold().strip()
        if normalized_query and normalized_query in content_folded:
            score += 3.0
        content_tokens = cls._memory_tokens(content)
        if content_tokens:
            score += len(query_tokens & content_tokens) * 1.2
        metadata = cls._memory_metadata(memory)
        for key in ("memory_key", "speaker_key", "speaker_global_key", "conversation_key"):
            value = str(metadata.get(key) or "")
            if value and query.casefold() in value.casefold():
                score += 0.8
        return score

    @classmethod
    def _memory_recency_score(cls, memory: dict[str, Any]) -> float:
        timestamp = cls._memory_timestamp(memory)
        if timestamp <= 0:
            return 0.0
        try:
            age_days = max(0.0, (datetime.now().timestamp() - timestamp) / 86400)
        except OSError:
            return 0.0
        if age_days <= 7:
            return 0.7
        if age_days <= 30:
            return 0.4
        if age_days <= 90:
            return 0.2
        return 0.0

    @classmethod
    def _memory_hybrid_rank_score(
        cls,
        memory: dict[str, Any],
        *,
        query: str,
        scope_rank: int,
    ) -> float:
        metadata = cls._memory_metadata(memory)
        verified_bonus = 1.0 if metadata.get("verified") is True else 0.0
        vector_score = max(0.0, 1.0 - cls._memory_distance(memory))
        return (
            scope_rank * 100.0
            + cls._memory_query_score(memory, query) * 8.0
            + LONG_TERM_MEMORY_TYPE_RANK.get(cls._memory_type(memory), 1) * 2.0
            + verified_bonus
            + cls._memory_recency_score(memory)
            + vector_score
        )

    @classmethod
    def _memory_usable(cls, memory: dict[str, Any]) -> bool:
        return (
            isinstance(memory, dict)
            and bool(str(memory.get("content") or "").strip())
            and not cls._memory_expired(memory)
            and not cls._memory_inactive(memory)
        )

    @staticmethod
    def _memory_conversation_key(memory: dict[str, Any]) -> str:
        metadata = memory.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        return scoped_memory_conversation_key(metadata)

    @staticmethod
    def _memory_scope_rank(
        memory: dict[str, Any],
        *,
        robot_id: str,
        conversation_key: str,
        speaker_global_key: str = "",
    ) -> int:
        return scoped_memory_scope_rank(
            memory,
            robot_id=robot_id,
            conversation_key=conversation_key,
            speaker_global_key=speaker_global_key,
        )

    def _collect_scoped_long_term_memory_candidates(
        self,
        *,
        store: Any,
        item_id: str,
        memory_type: str | None,
        robot_id: str,
        conversation_key: str,
        speaker_global_key: str,
    ) -> list[dict[str, Any]]:
        memory_types = (memory_type,) if memory_type else LONG_TERM_MEMORY_TYPE_ORDER
        candidates: list[dict[str, Any]] = []
        for current_type in memory_types:
            try:
                memories = store.get_all_memories(item_id, memory_type=current_type)
            except Exception as exc:
                logger.debug(
                    "[RobotMCP] Failed to load scoped memory candidates item=%s type=%s: %s",
                    item_id,
                    current_type,
                    exc,
                )
                continue
            for memory in memories:
                if not self._memory_usable(memory):
                    continue
                if self._memory_scope_rank(
                    memory,
                    robot_id=robot_id,
                    conversation_key=conversation_key,
                    speaker_global_key=speaker_global_key,
                ) < 0:
                    continue
                candidates.append(memory)
        return candidates

    def _select_recalled_long_term_memories(
        self,
        *,
        query: str,
        limit: int,
        memories: list[dict[str, Any]],
        robot_id: str,
        conversation_key: str,
        speaker_global_key: str,
    ) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for memory in memories:
            if not self._memory_usable(memory):
                continue
            memory_id = str(memory.get("id") or "").strip()
            content = str(memory.get("content") or "").strip()
            key = memory_id or f"content:{content}"
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = memory
                continue
            if existing.get("distance") is None and memory.get("distance") is not None:
                by_key[key] = {**existing, "distance": memory.get("distance")}

        ranked: list[tuple[float, str, dict[str, Any]]] = []
        for memory in by_key.values():
            scope_rank = self._memory_scope_rank(
                memory,
                robot_id=robot_id,
                conversation_key=conversation_key,
                speaker_global_key=speaker_global_key,
            )
            if scope_rank < 0:
                continue
            ranked.append(
                (
                    self._memory_hybrid_rank_score(
                        memory,
                        query=query,
                        scope_rank=scope_rank,
                    ),
                    str(memory.get("id") or ""),
                    memory,
                )
            )

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [memory for _, _, memory in ranked[:limit]]

    def _save_memory(self, args: dict) -> list[dict[str, str]]:
        content = sanitize_robot_visible_text(str(args.get("content") or "")).strip()
        if not content:
            return [{"type": "text", "text": "Error: content required"}]

        memory_type = str(args.get("memory_type") or "fact").strip() or "fact"
        if memory_type not in LONG_TERM_MEMORY_TYPES:
            return [{"type": "text", "text": f"Error: invalid memory_type: {memory_type}"}]

        item_id = str(args.get("_termman_item_id") or args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id unavailable"}]

        try:
            from app.services.agent.prompts import policy as memory_policy

            if memory_policy.should_reject_long_term_memory(content):
                return [
                    {
                        "type": "text",
                        "text": "Memory not saved: content is too long, noisy, sensitive, or empty.",
                    }
                ]

            default_ttl_days = memory_policy.resolve_memory_ttl_days(memory_type)
            raw_ttl_days = args.get("ttl_days")
            if raw_ttl_days in (None, ""):
                ttl_days = default_ttl_days
            else:
                ttl_days = int(raw_ttl_days)
            ttl_days = max(1, min(3650, ttl_days))

            context_token = str(args.get("_robot_context_token") or "").strip()
            context = get_robot_mcp_context(context_token)
            active_target = self._context_target_from_active_context(context)
            conversation_key = ""
            robot_id = ""
            sender_key = ""
            if context is not None:
                robot_id = str(context.robot_id or "").strip()
                sender_key = str(context.sender_key or "").strip()
                conversation_key = str(
                    getattr(context, "conversation_key", "")
                    or (active_target or {}).get("conversation")
                    or ""
                ).strip()

            metadata: dict[str, Any] = {
                "type": "robot_agent_saved",
                "source": "qq_robot_agent",
                "verified": False,
                "content_hash": memory_policy._build_content_hash(content),
            }
            memory_key = memory_policy.infer_memory_key(content, memory_type)
            if memory_key:
                metadata["memory_key"] = memory_key
            if robot_id:
                metadata["robot_id"] = robot_id
            if conversation_key:
                metadata["robot_conversation_key"] = conversation_key
                metadata["conversation_key"] = conversation_key
            if sender_key:
                metadata["speaker_key"] = sender_key
            speaker_global_key = speaker_global_key_from_context(
                sender_key,
                getattr(context, "reply_target", None) if context is not None else None,
            )
            if speaker_global_key:
                metadata["speaker_global_key"] = speaker_global_key
            metadata["memory_scope"] = memory_scope_for_content(content, memory_type)

            candidate = memory_policy.MemoryCandidate(
                content=content,
                memory_type=memory_type,
                ttl_days=ttl_days,
                metadata=metadata,
            )

            from app.services.agent.memory.vector_store import vector_store

            memory_id = memory_policy.persist_memory_candidate(
                item_id,
                candidate,
                store=vector_store,
            )
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

        if not memory_id:
            return [{"type": "text", "text": "Memory not saved: duplicate or rejected."}]
        return [
            {
                "type": "text",
                "text": f"Memory saved to TermMan long-term memory (ID: {str(memory_id)[:8]}...).",
            }
        ]

    def _recall_memory(self, args: dict) -> list[dict[str, str]]:
        query = str(args.get("query") or "").strip()
        if not query:
            return [{"type": "text", "text": "Error: query required"}]

        memory_type = str(args.get("memory_type") or "").strip() or None
        if memory_type is not None and memory_type not in LONG_TERM_MEMORY_TYPES:
            return [{"type": "text", "text": f"Error: invalid memory_type: {memory_type}"}]

        item_id = str(args.get("_termman_item_id") or args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id unavailable"}]

        context_token = str(args.get("_robot_context_token") or "").strip()
        context = get_robot_mcp_context(context_token)
        active_target = self._context_target_from_active_context(context)
        conversation_key = ""
        robot_id = ""
        speaker_global_key = ""
        if context is not None:
            robot_id = str(context.robot_id or "").strip()
            conversation_key = str(
                getattr(context, "conversation_key", "")
                or (active_target or {}).get("conversation")
                or ""
            ).strip()
            speaker_global_key = speaker_global_key_from_context(
                str(getattr(context, "sender_key", "") or ""),
                getattr(context, "reply_target", None),
            )

        limit = self._long_term_memory_limit(args)
        try:
            from app.services.agent.memory.vector_store import vector_store

            vector_memories = vector_store.search_memories(
                item_id=item_id,
                query=query,
                n_results=limit * LONG_TERM_MEMORY_CANDIDATE_MULTIPLIER,
                memory_type=memory_type,
                include_expired=False,
                active_only=True,
            )
            scoped_memories = self._collect_scoped_long_term_memory_candidates(
                store=vector_store,
                item_id=item_id,
                memory_type=memory_type,
                robot_id=robot_id,
                conversation_key=conversation_key,
                speaker_global_key=speaker_global_key,
            )
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

        selected = self._select_recalled_long_term_memories(
            query=query,
            limit=limit,
            memories=[*vector_memories, *scoped_memories],
            robot_id=robot_id,
            conversation_key=conversation_key,
            speaker_global_key=speaker_global_key,
        )
        if not selected:
            scope = f" for {conversation_key}" if conversation_key else ""
            return [
                {
                    "type": "text",
                    "text": f"No TermMan long-term memory matched {query!r}{scope}.",
                }
            ]

        lines = [
            "TermMan long-term memory "
            f"({len(selected)} result(s)"
        ]
        if conversation_key:
            lines[0] += f", current QQ {conversation_key}"
        lines[0] += "):"
        for memory in selected:
            metadata = memory.get("metadata") or {}
            tags = [str(metadata.get("memory_type") or "fact")]
            status = str(metadata.get("status") or "").strip()
            if status:
                tags.append(status)
            if metadata.get("verified") is True:
                tags.append("verified")
            memory_conversation_key = self._memory_conversation_key(memory)
            if memory_conversation_key:
                tags.append(memory_conversation_key)
            content = sanitize_robot_visible_text(str(memory.get("content") or "")).strip()
            if not content:
                continue
            lines.append(
                f"- [{', '.join(tags)}{self._memory_similarity_label(memory)}] {content}"
            )
        return [{"type": "text", "text": "\n".join(lines)}]

    def _read_conversation_memory(self, args: dict) -> list[dict[str, str]]:
        context_token = str(args.get("_robot_context_token") or "").strip()
        context = get_robot_mcp_context(context_token)
        try:
            explicit_target = self._build_explicit_target(args)
            conversation_target = self._build_conversation_target(args)
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

        target: RobotReplyTarget | None = None
        fallback_robot_id = ""
        if context is not None:
            active_target = self._context_target_from_active_context(context)
            if active_target is None:
                return [
                    {
                        "type": "text",
                        "text": (
                            "Error: current QQ conversation memory is unavailable "
                            "for this target type."
                        ),
                    }
                ]
            requested_target = explicit_target or conversation_target
            if requested_target is not None and not self._same_target(
                requested_target,
                active_target,
            ):
                return [
                    {
                        "type": "text",
                        "text": self._active_context_memory_target_error(active_target),
                    }
                ]
            context_reference = str(
                args.get("reply_to") or args.get("conversation") or ""
            ).strip()
            if context_reference and not self._reference_matches_active_target(
                context_reference,
                active_target,
            ):
                return [
                    {
                        "type": "text",
                        "text": self._active_context_memory_target_error(active_target),
                    }
                ]
            robot_id = context.robot_id
            conversation_key = active_target["conversation"]
        else:
            if explicit_target is not None:
                target = explicit_target
            else:
                try:
                    target, fallback_robot_id = self._resolve_context_target(args)
                except Exception as exc:
                    if conversation_target is None:
                        return [{"type": "text", "text": f"Error: {exc}"}]
                    target = conversation_target
                if target is None and conversation_target is not None:
                    target = conversation_target
            if target is None:
                return [
                    {
                        "type": "text",
                        "text": (
                            "Error: no active robot conversation context and no "
                            "matching QQ conversation memory target. Use reply_to "
                            "or conversation from visible context, or provide "
                            "target_type, target_id, and robot_id."
                        ),
                    }
                ]
            try:
                robot_id = self._get_accessible_robot_id(
                    args,
                    fallback_robot_id=fallback_robot_id,
                )
            except Exception as exc:
                return [{"type": "text", "text": f"Error: {exc}"}]
            from app.plugins.robot.conversation_memory import (
                conversation_key_from_reply_target,
            )

            conversation_key = conversation_key_from_reply_target(target)

        line_cap = (
            ACTIVE_CONTEXT_MEMORY_MAX_LINES
            if context is not None
            else GENERAL_MEMORY_MAX_LINES
        )
        lines = self._memory_line_limit(args, max_lines=line_cap)
        query = str(args.get("query") or "").strip()
        from app.plugins.robot.conversation_memory import (
            normalize_conversation_key,
            robot_conversation_memory,
        )

        conversation_key = normalize_conversation_key(conversation_key)
        try:
            if query:
                memory = self._filter_memory_lines(
                    robot_conversation_memory.read(robot_id, conversation_key),
                    query,
                    lines=lines,
                )
                scope = f"matching query {query!r}"
            else:
                memory = robot_conversation_memory.read_recent(
                    robot_id,
                    conversation_key,
                    lines=lines,
                )
                scope = f"recent {lines} line(s)"
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

        memory = sanitize_robot_visible_text(memory)
        if not memory.strip():
            if query:
                return [
                    {
                        "type": "text",
                        "text": (
                            "No QQ conversation .log memory matched "
                            f"{query!r} for {conversation_key}."
                        ),
                    }
                ]
            return [
                {
                    "type": "text",
                    "text": (
                        "No QQ conversation .log memory found for "
                        f"{conversation_key}."
                    ),
                }
            ]
        return [
            {
                "type": "text",
                "text": (
                    "QQ conversation .log memory "
                    f"({conversation_key}, {scope}):\n{memory}"
                ),
            }
        ]

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: callable,
        skip_memory: bool = False,
    ) -> None:
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler,
            "skip_memory": skip_memory,
        }

    def _send_message(self, args: dict) -> list[dict[str, str]]:
        raw_messages = self._raw_message_texts(args)
        messages = self._sanitize_outgoing_messages(raw_messages)
        text = "\n".join(messages).strip()
        raw_text = "\n".join(str(value or "") for value in raw_messages).strip()
        if not messages:
            if any(is_robot_internal_trace_text(str(value or "")) for value in raw_messages):
                return [
                    {
                        "type": "text",
                        "text": "No QQ message sent: internal tool trace.",
                    }
                ]
            if any(is_no_reply_intent(str(value or "")) for value in raw_messages):
                return [
                    {
                        "type": "text",
                        "text": "No QQ message sent: no reply needed.",
                    }
                ]
            return [{"type": "text", "text": "Error: text required"}]
        if is_no_reply_intent(raw_text) and raw_text == text:
            return [
                {
                    "type": "text",
                    "text": "No QQ message sent: no reply needed.",
                }
            ]
        if any(is_robot_internal_trace_text(message) for message in messages):
            return [
                {
                    "type": "text",
                    "text": "No QQ message sent: internal tool trace.",
                }
            ]

        context_token = str(args.get("_robot_context_token") or "").strip()
        context = get_robot_mcp_context(context_token)
        try:
            explicit_target = self._build_explicit_target(args)
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]
        broadcast = bool(args.get("broadcast"))
        if broadcast and explicit_target is not None:
            return [
                {
                    "type": "text",
                    "text": (
                        "Error: broadcast uses QQ conversations from context; "
                        "do not combine it with target_type/target_id."
                    ),
                }
            ]

        context_target: RobotReplyTarget | None = None
        context_target_robot_id = ""
        context_reference = self._context_reference(args)
        active_context_override_error = self._active_context_target_override_error(
            context=context,
            explicit_target=explicit_target,
            broadcast=broadcast,
            context_reference=context_reference,
        )
        if active_context_override_error:
            return [{"type": "text", "text": active_context_override_error}]
        active_context_delivery_error = self._active_context_delivery_error(context)
        if active_context_delivery_error:
            return [{"type": "text", "text": active_context_delivery_error}]
        if context is not None:
            explicit_target = None
            context_reference = ""

        if explicit_target is None and not broadcast and (context is None or context_reference):
            try:
                context_target, context_target_robot_id = self._resolve_context_target(args)
            except Exception as exc:
                return [{"type": "text", "text": f"Error: {exc}"}]

        if context is None and explicit_target is None and context_target is None and not broadcast:
            return [
                {
                    "type": "text",
                    "text": (
                        "Error: no active robot conversation context and no "
                        "matching QQ target in chat context. Use reply_to to choose "
                        "a QQ conversation from context, or provide target_type and "
                        "target_id if the target is outside the current context."
                    ),
                }
            ]

        attempted_robot_id = ""
        attempted_target: RobotReplyTarget | None = None
        attempted_mode = ""
        try:
            from app.plugins.robot.bridge_client import robot_bridge_client

            if broadcast:
                sent = self._broadcast_context_targets(
                    args=args,
                    text=text,
                    context=context,
                )
                return [
                    {
                        "type": "text",
                        "text": f"Broadcast sent to {len(sent)} QQ conversation(s).",
                    }
                ]

            if explicit_target is not None:
                robot_id = self._get_accessible_robot_id(
                    args,
                    fallback_robot_id=context.robot_id if context else "",
                )
                attempted_robot_id = robot_id
                attempted_target = explicit_target
                attempted_mode = "explicit_target"
                self._record_tool_send_event(
                    robot_id=robot_id,
                    target=explicit_target,
                    text=text,
                    mode="explicit_target",
                    args=args,
                )
                if self._single_text_too_long_for_group(args, explicit_target, messages):
                    return [
                        {
                            "type": "text",
                            "text": self._group_single_text_too_long_error(messages[0]),
                        }
                    ]
                self._send_messages(robot_bridge_client, robot_id, explicit_target, messages)
                self._remember_sent_messages(robot_id, explicit_target, messages)
                return [
                    {
                        "type": "text",
                        "text": (
                            f"Message sent to QQ {explicit_target.target_type} "
                            f"{explicit_target.target_id}."
                        ),
                    }
                ]

            if context_target is not None:
                fallback_robot_id = context_target_robot_id
                if not fallback_robot_id and context is not None:
                    fallback_robot_id = context.robot_id
                robot_id = self._get_accessible_robot_id(
                    args,
                    fallback_robot_id=fallback_robot_id,
                )
                attempted_robot_id = robot_id
                attempted_target = context_target
                attempted_mode = "context_target"
                self._record_tool_send_event(
                    robot_id=robot_id,
                    target=context_target,
                    text=text,
                    mode="context_target",
                    args=args,
                )
                if self._single_text_too_long_for_group(args, context_target, messages):
                    return [
                        {
                            "type": "text",
                            "text": self._group_single_text_too_long_error(messages[0]),
                        }
                    ]
                self._send_messages(robot_bridge_client, robot_id, context_target, messages)
                self._remember_sent_messages(robot_id, context_target, messages)
                return [
                    {
                        "type": "text",
                        "text": (
                            f"Message sent to QQ {context_target.target_type} "
                            f"{context_target.target_id} from chat context."
                        ),
                    }
                ]

            if context is None:
                return [{"type": "text", "text": "Error: robot context unavailable"}]

            attempted_robot_id = context.robot_id
            attempted_target = context.reply_target
            attempted_mode = "current_context"
            self._record_tool_send_event(
                robot_id=context.robot_id,
                target=context.reply_target,
                text=text,
                mode="current_context",
                args=args,
            )
            if self._single_text_too_long_for_group(args, attempted_target, messages):
                return [
                    {
                        "type": "text",
                        "text": self._group_single_text_too_long_error(messages[0]),
                    }
                ]
            self._send_messages(
                robot_bridge_client,
                attempted_robot_id,
                attempted_target.model_copy(deep=True),
                messages,
            )
            self._remember_sent_messages(attempted_robot_id, attempted_target, messages)
            return [{"type": "text", "text": "Message sent to current robot conversation."}]
        except Exception as exc:
            logger.warning("[RobotMCPServer] Failed to send robot message: %s", exc)
            if attempted_robot_id and attempted_target is not None:
                self._record_tool_send_event(
                    robot_id=attempted_robot_id,
                    target=attempted_target,
                    text=text,
                    mode=attempted_mode or "unknown",
                    args=args,
                    status="error",
                    error=str(exc),
                )
            return [{"type": "text", "text": f"Error: {exc}"}]

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
                "skip_memory": tool.get("skip_memory", False),
            }
            for tool in self._tools.values()
        ]

    def call_tool(self, name: str, args: dict) -> list[dict[str, str]]:
        if name not in self._tools:
            return [{"type": "text", "text": f"Tool '{name}' not found"}]
        try:
            return self._tools[name]["handler"](args)
        except Exception as exc:
            logger.warning("[RobotMCPServer] Tool '%s' failed: %s", name, exc)
            return [{"type": "text", "text": f"Error: {exc}"}]

    async def run(self) -> None:
        logger.info("[RobotMCPServer] Starting stdio server")
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                request = json.loads(line.strip())
                response = await self._handle_request(request)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError as exc:
                sys.stdout.write(json.dumps({"error": f"Invalid JSON: {exc}"}) + "\n")
                sys.stdout.flush()
            except Exception as exc:
                sys.stdout.write(json.dumps({"error": str(exc)}) + "\n")
                sys.stdout.flush()

    async def _handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "termman-robot", "version": "1.0.0"},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": self.list_tools()},
            }

        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": self.call_tool(
                        params.get("name", ""),
                        params.get("arguments", {}),
                    )
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


robot_mcp_server = RobotMCPServer()


def main() -> None:
    asyncio.run(robot_mcp_server.run())


if __name__ == "__main__":
    main()
