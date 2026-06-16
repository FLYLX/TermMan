from __future__ import annotations

from .contracts import RobotReplyTarget

DEFAULT_GROUP_MESSAGE_CHUNK_CHARS = 40
_GROUP_TARGET_TYPES = {"group", "qq_group"}
_PRIVATE_OR_CHANNEL_TARGET_TYPES = {
    "private",
    "friend",
    "user",
    "direct",
    "c2c",
    "channel",
    "guild",
}


def _normalized_type(value: object) -> str:
    return str(value or "").strip().lower()


def _is_group_data(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    for key in ("type", "target_type", "conversation_type", "message_type"):
        if _normalized_type(data.get(key)) == "group":
            return True
    return bool(str(data.get("group_id") or "").strip())


def _is_private_or_channel_data(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    for key in ("type", "target_type", "conversation_type", "message_type"):
        if _normalized_type(data.get(key)) in _PRIVATE_OR_CHANNEL_TARGET_TYPES:
            return True
    return bool(data.get("private") or data.get("channel"))


def is_group_reply_target(target: RobotReplyTarget) -> bool:
    target_type = _normalized_type(target.target_type)
    if target_type in _GROUP_TARGET_TYPES:
        return True
    if target_type in _PRIVATE_OR_CHANNEL_TARGET_TYPES:
        return False

    metadata = target.metadata if isinstance(target.metadata, dict) else {}
    conversation_data = metadata.get("conversation")
    if _is_group_data(conversation_data):
        return True
    if _is_private_or_channel_data(conversation_data):
        return False

    target_data = metadata.get("target")
    if _is_group_data(target_data):
        return True
    return False


def split_group_message_text(
    text: str,
    *,
    max_chars: int = DEFAULT_GROUP_MESSAGE_CHUNK_CHARS,
) -> list[str]:
    _ = max_chars
    normalized = str(text or "").strip()
    if not normalized:
        return []
    return [normalized]


def split_robot_message_for_target(
    target: RobotReplyTarget,
    text: str,
    *,
    max_chars: int = DEFAULT_GROUP_MESSAGE_CHUNK_CHARS,
) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    if not is_group_reply_target(target):
        return [normalized]
    return split_group_message_text(normalized, max_chars=max_chars)
