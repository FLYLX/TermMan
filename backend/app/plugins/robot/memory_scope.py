from __future__ import annotations

import re
from typing import Any

from app.plugins.robot.contracts import RobotReplyTarget

SPEAKER_SCOPED_MEMORY_TYPES = {"fact", "preference"}
CONVERSATION_SCOPED_MEMORY_TYPES = {"context", "error"}


def memory_content_is_question_like(content: str) -> bool:
    normalized = str(content or "").strip()
    if not normalized:
        return False
    if "?" in normalized or "？" in normalized:
        return True
    payload = re.sub(r"^[^:：\n]{1,100}[:：]\s*", "", normalized)
    return bool(
        re.match(
            r"^(?:谁|谁是|还有谁|哪些|哪个|什么|怎么|为什么|是否|是不是|记得|知道)",
            payload,
        )
        or re.search(
            r"(?:还有谁|谁是|是谁|有谁|哪些人?|哪个|什么)(?:吗|呢)?",
            payload,
        )
    )


def memory_query_requests_enumeration(query: str) -> bool:
    normalized = re.sub(r"\s+", "", str(query or "")).casefold()
    return any(
        cue in normalized
        for cue in ("还有谁", "谁是", "哪些", "都有谁", "全部", "所有", "list all")
    )


def speaker_global_key_from_context(
    sender_key: str = "",
    reply_target: RobotReplyTarget | None = None,
) -> str:
    platform = ""
    sender_key = str(sender_key or "").strip()
    if ":" in sender_key:
        platform = sender_key.split(":", 1)[0].strip()

    user_id = ""
    metadata = reply_target.metadata if reply_target is not None else {}
    if isinstance(metadata, dict):
        sender_data = metadata.get("sender")
        if isinstance(sender_data, dict):
            user_id = str(sender_data.get("user_id") or "").strip()
            platform = str(sender_data.get("platform") or platform).strip()
        if not user_id:
            target_data = metadata.get("target")
            if isinstance(target_data, dict):
                user_id = str(target_data.get("user_id") or "").strip()
                platform = str(target_data.get("platform") or platform).strip()

    if not user_id and sender_key:
        parts = [part for part in sender_key.split(":") if part]
        if len(parts) >= 3:
            platform = platform or parts[0]
            user_id = parts[-1]

    if not user_id:
        return ""
    return f"{platform or 'unknown'}:user:{user_id}"


def memory_conversation_key(metadata: dict[str, Any]) -> str:
    return str(
        metadata.get("robot_conversation_key")
        or metadata.get("conversation_key")
        or ""
    ).strip()


def memory_speaker_global_key(metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("speaker_global_key") or "").strip()
    if explicit:
        return explicit
    return speaker_global_key_from_context(str(metadata.get("speaker_key") or ""))


def memory_scope_for_content(content: str, memory_type: str) -> str:
    normalized_type = str(memory_type or "").strip()
    if normalized_type in CONVERSATION_SCOPED_MEMORY_TYPES:
        return "conversation"
    normalized = str(content or "").strip().lower()
    payload = re.sub(r"^[^:：\n]{1,80}[:：]\s*", "", normalized)
    if any(token in payload for token in ("你叫", "你是", "bot name", "robot name")):
        return "robot"
    if normalized_type == "preference":
        return "speaker"
    if normalized_type == "fact":
        if re.search(
            r"^(?:我|本人|咱|俺)(?:叫|是|住在|来自|喜欢|不喜欢|讨厌|的)",
            payload,
        ):
            return "speaker"
        if re.search(
            r"(?:猫娘|主人|管理员|群主|昵称|外号|名字|身份|本人)"
            r"[\s\S]{0,48}(?:是|就是|为|叫|自称|被称为|指的是|对应)"
            r"|(?:是|就是|为|叫|自称|被称为|指的是|对应)[\s\S]{0,48}"
            r"(?:猫娘|主人|管理员|群主|昵称|外号|名字|身份|本人)",
            payload,
        ):
            return "conversation"
        if re.search(
            r"(?:@QQ\([^)]+\)|^[\u4e00-\u9fffA-Za-z0-9_·.-]{1,32}\s*)"
            r"(?:是|就是|叫|指的是|对应)",
            payload,
        ):
            return "conversation"
        return "speaker"
    return "conversation"


def memory_scope_rank(
    memory: dict[str, Any],
    *,
    robot_id: str,
    conversation_key: str,
    speaker_global_key: str = "",
) -> int:
    metadata = memory.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    memory_robot_id = str(metadata.get("robot_id") or "").strip()
    if memory_robot_id and robot_id and memory_robot_id != robot_id:
        return -1

    memory_type = str(metadata.get("memory_type") or "").strip()
    scope = str(metadata.get("memory_scope") or "").strip()
    memory_conversation = memory_conversation_key(metadata)
    memory_speaker = memory_speaker_global_key(metadata)

    if scope == "conversation":
        return 4 if memory_conversation and memory_conversation == conversation_key else -1
    if scope == "speaker":
        if memory_type == "fact":
            # The speaker key records who supplied the fact, not necessarily the
            # person the fact describes. Facts said in a group are shared group
            # knowledge; the same speaker can still recall them across groups.
            if memory_speaker and speaker_global_key and memory_speaker == speaker_global_key:
                return 5
            if memory_conversation and memory_conversation == conversation_key:
                return 4
            return -1
        if memory_speaker:
            return 5 if speaker_global_key and memory_speaker == speaker_global_key else -1
        # Legacy speaker-scoped records may not have a stable speaker key.
        return 3 if memory_conversation and memory_conversation == conversation_key else -1
    if scope == "robot":
        return 2 if (memory_robot_id or not robot_id) else -1

    if memory_speaker and memory_type in SPEAKER_SCOPED_MEMORY_TYPES:
        return 5 if speaker_global_key and memory_speaker == speaker_global_key else -1
    if memory_conversation:
        if memory_conversation == conversation_key:
            return 4
        return -1
    if speaker_global_key and memory_speaker == speaker_global_key:
        return 5
    if memory_robot_id:
        return 2
    return 1
