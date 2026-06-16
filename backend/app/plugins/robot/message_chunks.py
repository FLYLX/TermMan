from __future__ import annotations

import re

from .contracts import RobotReplyTarget

DEFAULT_GROUP_MESSAGE_CHUNK_CHARS = 40
MIN_SOFT_SPLIT_CHARS = 18

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;])")
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
_SOFT_SPLIT_SEPARATORS = ("\n", "。", "！", "？", "；", ";", "，", ",", "、", "：", ":", " ")
_RIGHT_ATTACHING_PUNCTUATION = set("，,。.!?！？；;：:、)]}）】」』")
_GROUP_TERMINAL_PERIODS = "。．."


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


def _is_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _join_piece(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left[-1].isspace() or right[0].isspace():
        return f"{left}{right}"
    if right[0] in _RIGHT_ATTACHING_PUNCTUATION:
        return f"{left}{right}"
    if left[-1] in "([{（【「『":
        return f"{left}{right}"
    if _is_cjk(left[-1]) or _is_cjk(right[0]):
        return f"{left}{right}"
    return f"{left} {right}"


def _best_soft_cut(text: str, max_chars: int) -> int:
    min_cut = min(max(MIN_SOFT_SPLIT_CHARS, max_chars // 2), max_chars)
    window = text[: max_chars + 1]
    for separator in _SOFT_SPLIT_SEPARATORS:
        index = window.rfind(separator)
        if index >= min_cut:
            return index + len(separator)
    return max_chars


def _split_long_piece(piece: str, *, max_chars: int) -> list[str]:
    chunks: list[str] = []
    remaining = piece.strip()
    while len(remaining) > max_chars:
        cut_at = _best_soft_cut(remaining, max_chars)
        chunk = remaining[:cut_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _casualize_group_chunk(chunk: str) -> str:
    return chunk.strip().rstrip(_GROUP_TERMINAL_PERIODS).strip()


def split_group_message_text(
    text: str,
    *,
    max_chars: int = DEFAULT_GROUP_MESSAGE_CHUNK_CHARS,
) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []

    safe_max_chars = max(1, int(max_chars or DEFAULT_GROUP_MESSAGE_CHUNK_CHARS))
    explicit_line_breaks = (
        len([line for line in normalized.splitlines() if line.strip()]) > 1
    )
    if len(normalized) <= safe_max_chars and not explicit_line_breaks:
        casual = _casualize_group_chunk(normalized)
        return [casual] if casual else []

    chunks: list[str] = []
    current = ""
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                chunks.append(current)
                current = ""
            continue

        for sentence in _SENTENCE_BOUNDARY_RE.split(line):
            sentence = sentence.strip()
            if not sentence:
                continue
            for piece in _split_long_piece(sentence, max_chars=safe_max_chars):
                candidate = _join_piece(current, piece)
                if current and len(candidate) > safe_max_chars:
                    chunks.append(current)
                    current = piece
                else:
                    current = candidate

        if explicit_line_breaks and current:
            casual = _casualize_group_chunk(current)
            if casual:
                chunks.append(casual)
            current = ""

    if current:
        chunks.append(current)
    return [chunk for chunk in (_casualize_group_chunk(chunk) for chunk in chunks) if chunk]


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
