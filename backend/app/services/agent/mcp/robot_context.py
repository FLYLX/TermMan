from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass

from app.plugins.robot.contracts import RobotReplyTarget


@dataclass(frozen=True)
class RobotMCPContext:
    robot_id: str
    sender_key: str
    reply_target: RobotReplyTarget


def _robot_conversation_type(reply_target: RobotReplyTarget, sender_key: str) -> str:
    target_data = reply_target.metadata.get("target")
    if isinstance(target_data, dict):
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
    target_data = reply_target.metadata.get("target")
    if isinstance(target_data, dict):
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
                "- send rule: `mcp_robot_send_message` will send only to this "
                "current conversation for this turn, not to any conversation "
                "shown in older history."
            ),
        ]
    )


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
