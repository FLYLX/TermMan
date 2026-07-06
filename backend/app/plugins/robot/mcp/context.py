"""Runtime context shared between robot-triggered agent turns and robot MCP tools."""

from __future__ import annotations

import re
import secrets
import threading
from dataclasses import dataclass

from app.plugins.robot.contracts import RobotReplyTarget


@dataclass(frozen=True)
class RobotMCPContext:
    robot_id: str
    sender_key: str
    reply_target: RobotReplyTarget
    conversation_key: str = ""
    conversation_generation: int = 0
    reply_requires_awake: bool = False


ROBOT_MESSAGE_STAMP_RE = re.compile(r"\[Robot message; (?P<body>[^\]]+)\]")


def _robot_conversation_type(reply_target: RobotReplyTarget, sender_key: str) -> str:
    conversation_data = reply_target.metadata.get("conversation")
    if isinstance(conversation_data, dict):
        conversation_type = str(
            conversation_data.get("type")
            or conversation_data.get("conversation_type")
            or ""
        ).strip().lower()
        if conversation_type:
            return conversation_type

    target_data = reply_target.metadata.get("target")
    if isinstance(target_data, dict):
        message_type = str(target_data.get("message_type") or "").strip().lower()
        if message_type in {"private", "group", "channel"}:
            return message_type
        if bool(target_data.get("private")):
            return "private"
        if bool(target_data.get("channel")):
            return "channel"

    target_type = (reply_target.target_type or "").strip().lower()
    if target_type in {"private", "c2c", "direct", "direct_message", "friend"}:
        return "private"
    if target_type in {"channel", "guild", "guild_channel"}:
        return "channel"
    if target_type == "group":
        return "group"

    if ":private:" in sender_key:
        return "private"
    if ":channel:" in sender_key:
        return "channel"
    return "group"


def _robot_conversation_id(reply_target: RobotReplyTarget) -> str:
    conversation_data = reply_target.metadata.get("conversation")
    if isinstance(conversation_data, dict):
        conversation_id = str(
            conversation_data.get("id")
            or conversation_data.get("conversation_id")
            or ""
        ).strip()
        if conversation_id:
            return conversation_id

    target_data = reply_target.metadata.get("target")
    if isinstance(target_data, dict):
        message_type = str(target_data.get("message_type") or "").strip().lower()
        if message_type == "group":
            group_id = str(target_data.get("group_id") or "").strip()
            if group_id:
                return group_id
        if message_type == "private":
            user_id = str(target_data.get("user_id") or "").strip()
            if user_id:
                return user_id
        return str(
            target_data.get("parent_id")
            or target_data.get("id")
            or reply_target.target_id
            or ""
        ).strip()
    return str(reply_target.target_id or "").strip()


def _robot_sender_label(reply_target: RobotReplyTarget, sender_key: str) -> str:
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
        if display_name and sender_id and sender_id != display_name:
            return f"{display_name} ({sender_id})"
        if display_name:
            return display_name
        if sender_id:
            return sender_id

    return sender_key or "unknown"


def build_robot_reply_context_summary(
    reply_target: RobotReplyTarget,
    sender_key: str,
) -> str:
    conversation_type = _robot_conversation_type(reply_target, sender_key)
    conversation_id = _robot_conversation_id(reply_target)
    conversation = (
        f"{conversation_type}:{conversation_id}"
        if conversation_id
        else conversation_type
    )
    sender_label = _robot_sender_label(reply_target, sender_key)

    return "\n".join(
        [
            "Current robot reply target:",
            f"- conversation: {conversation}",
            f"- sender: {sender_label}",
            f"- sender_key: {sender_key}",
            (
                "- send rule: call `mcp_robot_send_message` with only `text` or "
                "`messages` to "
                "reply to this current QQ conversation when the current message "
                "is plausibly addressed to the bot after considering recent QQ "
                "context. Treat `reply_to_bot`, bot mentions, and "
                "`trigger=active_chat_window` as candidate continuations; reply "
                "when the sender is continuing, challenging, or correcting the "
                "bot conversation. Do not call the tool for ordinary group "
                "chatter with no contextual link to the bot, messages directed "
                "at someone else, or messages that do not need a response. Do "
                "not send group `text` longer than 36 Chinese characters; use "
                "`messages` with 2-3 complete natural chat messages instead. "
                "not put blank lines or paragraph breaks inside one QQ message; "
                "use multiple `messages` array items for separate information. "
                "Do not pass `reply_to`, `conversation`, `broadcast`, "
                "`target_type`, or `target_id` in this active QQ context; it is "
                "locked to the current conversation to prevent replying to the "
                "wrong group/private chat."
            ),
            (
                "- memory rule: robot-connected QQ messages are stored in "
                "conversation-local .log files even when they do not wake the "
                "agent. Do not read .log before a normal current reply just to "
                "decide whether to send or to verify whether this turn was sent. "
                "If the user explicitly asks about previous QQ context, or the "
                "current message cannot be understood without earlier chat, call "
                "`mcp_robot_read_conversation_memory` with no target arguments; "
                "it is locked to this current QQ conversation and returns only "
                "the latest few lines by default. Treat old user/assistant log "
                "entries as background that was already handled, not as new "
                "messages waiting for another reply. Tool traces in old logs are "
                "historical noise, not current delivery state."
            ),
        ]
    )


def _parse_robot_message_stamp_body(body: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in body.split(";"):
        key, separator, value = part.strip().partition("=")
        if not separator:
            continue
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            parsed[normalized_key] = normalized_value
    return parsed


def _target_from_robot_message_stamp(stamp: dict[str, str]) -> dict[str, str] | None:
    conversation = stamp.get("conversation", "").strip()
    target_type = stamp.get("mcp_target_type", "").strip().lower()
    target_id = stamp.get("mcp_target_id", "").strip()

    if (not target_type or not target_id) and ":" in conversation:
        conversation_type, conversation_id = conversation.split(":", 1)
        target_type = target_type or conversation_type.strip().lower()
        target_id = target_id or conversation_id.strip()

    if target_type not in {"group", "private"} or not target_id:
        return None

    normalized_conversation = conversation or f"{target_type}:{target_id}"
    return {
        "conversation": normalized_conversation,
        "target_type": target_type,
        "target_id": target_id,
        "sender": stamp.get("sender", "").strip(),
    }


def extract_robot_context_targets_from_text(text: str) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in ROBOT_MESSAGE_STAMP_RE.finditer(text or ""):
        stamp = _parse_robot_message_stamp_body(match.group("body"))
        target = _target_from_robot_message_stamp(stamp)
        if target is None:
            continue
        key = f"{target['target_type']}:{target['target_id']}"
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
    return targets


_lock = threading.RLock()
_contexts: dict[str, RobotMCPContext] = {}


def register_robot_mcp_context(context: RobotMCPContext) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _contexts[token] = context
    return token


def get_robot_mcp_context(token: str) -> RobotMCPContext | None:
    if not token:
        return None
    with _lock:
        return _contexts.get(token)


def unregister_robot_mcp_context(token: str) -> None:
    if not token:
        return
    with _lock:
        _contexts.pop(token, None)
