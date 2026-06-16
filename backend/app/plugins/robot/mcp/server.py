from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any

from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.internal_trace import (
    is_robot_internal_trace_text,
    sanitize_robot_visible_text,
)
from app.plugins.robot.mcp.context import get_robot_mcp_context
from app.plugins.robot.reply_intent import is_no_reply_intent

logger = logging.getLogger(__name__)


class RobotMCPServer:
    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        self.register_tool(
            name="send_message",
            description=(
                "Send a concise message through the TermMan NoneBot/NapCat QQ robot. "
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
                            "Single QQ message text. Use this for one-message "
                            "replies."
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
                            "use this for long logs or summaries."
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
                        "description": "Maximum recent or matching log lines to return.",
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
            text = sanitize_robot_visible_text(str(raw_message or ""))
            if text and not is_no_reply_intent(text) and not is_robot_internal_trace_text(text):
                messages.append(text)
        return messages

    @staticmethod
    def _memory_line_limit(args: dict) -> int:
        raw_value = args.get("lines") or args.get("limit") or 80
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 80
        return max(1, min(500, value))

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

        lines = self._memory_line_limit(args)
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
