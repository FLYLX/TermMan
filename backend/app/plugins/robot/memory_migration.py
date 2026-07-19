from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.plugins.robot.memory_scope import (
    memory_conversation_key,
    memory_scope_for_content,
    memory_speaker_global_key,
    speaker_global_key_from_context,
)

logger = logging.getLogger(__name__)

ROBOT_MEMORY_SCHEMA_VERSION = 3
ROBOT_MEMORY_MIGRATION_INTERVAL_SECONDS = 300.0
SUPPORTED_MEMORY_TYPES = {"fact", "preference", "error", "context"}
KNOWN_MEMORY_SCOPES = {"speaker", "conversation", "robot", "legacy"}
QQ_SPEAKER_PREFIX_RE = re.compile(
    r"(?:@QQ[（(]|^[^:：\n]{0,80}[（(])(?P<qq>\d{5,12})[）)]"
)

_migration_lock = threading.RLock()
_migration_last_checked: dict[str, float] = {}


def _legacy_conversation_key(metadata: dict[str, Any]) -> str:
    existing = memory_conversation_key(metadata)
    if existing:
        return existing
    conversation = metadata.get("conversation")
    if isinstance(conversation, dict):
        conversation_type = str(
            conversation.get("type")
            or conversation.get("target_type")
            or conversation.get("conversation_type")
            or ""
        ).strip().lower()
        conversation_id = str(
            conversation.get("id")
            or conversation.get("target_id")
            or conversation.get("conversation_id")
            or ""
        ).strip()
        if conversation_type in {"group", "private"} and conversation_id:
            return f"{conversation_type}:{conversation_id}"
    raw_conversation = str(conversation or "").strip()
    if raw_conversation.startswith(("group:", "private:")):
        return raw_conversation
    return ""


def _legacy_speaker_global_key(
    content: str,
    metadata: dict[str, Any],
    *,
    inferred_scope: str,
) -> str:
    existing = memory_speaker_global_key(metadata)
    if existing:
        return existing

    sender = metadata.get("sender")
    if isinstance(sender, dict):
        user_id = str(
            sender.get("user_id") or sender.get("qq") or sender.get("id") or ""
        ).strip()
        platform = str(sender.get("platform") or "onebot_v11").strip()
        if user_id:
            return f"{platform}:user:{user_id}"

    speaker_key = str(metadata.get("speaker_key") or "").strip()
    if speaker_key:
        return speaker_global_key_from_context(speaker_key)

    if inferred_scope != "speaker":
        return ""
    match = QQ_SPEAKER_PREFIX_RE.search(str(content or "").strip())
    if match:
        return f"onebot_v11:user:{match.group('qq')}"
    return ""


def build_legacy_memory_metadata_upgrade(memory: dict[str, Any]) -> dict[str, Any]:
    content = str(memory.get("content") or "").strip()
    metadata = memory.get("metadata") or {}
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    memory_type = str(metadata.get("memory_type") or "fact").strip() or "fact"
    if memory_type not in SUPPORTED_MEMORY_TYPES:
        return {}
    try:
        current_version = int(metadata.get("robot_memory_schema_version") or 0)
    except (TypeError, ValueError):
        current_version = 0
    if current_version >= ROBOT_MEMORY_SCHEMA_VERSION:
        return {}

    conversation_key = _legacy_conversation_key(metadata)
    inferred_scope = memory_scope_for_content(content, memory_type)
    speaker_global_key = _legacy_speaker_global_key(
        content,
        metadata,
        inferred_scope=inferred_scope,
    )
    robot_id = str(metadata.get("robot_id") or metadata.get("robot_uuid") or "").strip()

    existing_scope = str(metadata.get("memory_scope") or "").strip()
    if (
        memory_type == "fact"
        and inferred_scope == "conversation"
        and conversation_key
    ):
        scope = "conversation"
    elif existing_scope in KNOWN_MEMORY_SCOPES:
        scope = existing_scope
    elif inferred_scope == "speaker" and (speaker_global_key or conversation_key):
        scope = "speaker"
    elif inferred_scope == "conversation" and conversation_key:
        scope = "conversation"
    elif inferred_scope == "robot" and robot_id:
        scope = "robot"
    else:
        scope = "legacy"

    updates: dict[str, Any] = {
        "robot_memory_schema_version": ROBOT_MEMORY_SCHEMA_VERSION,
        "memory_scope": scope,
        "legacy_memory_upgraded_at": datetime.now(timezone.utc).isoformat(),
    }
    if conversation_key:
        updates["robot_conversation_key"] = conversation_key
        updates["conversation_key"] = conversation_key
    if speaker_global_key:
        updates["speaker_global_key"] = speaker_global_key
    if robot_id:
        updates["robot_id"] = robot_id
    if scope == "legacy":
        updates["legacy_memory_unscoped"] = True
    return updates


def ensure_legacy_robot_memories_upgraded(
    item_id: str,
    *,
    store: Any,
    interval_seconds: float = ROBOT_MEMORY_MIGRATION_INTERVAL_SECONDS,
) -> dict[str, int]:
    normalized_item_id = str(item_id or "").strip()
    if not normalized_item_id:
        return {"checked": 0, "upgraded": 0, "deduplicated": 0, "failed": 0}

    now = time.monotonic()
    with _migration_lock:
        last_checked = _migration_last_checked.get(normalized_item_id, 0.0)
        if interval_seconds > 0 and now - last_checked < interval_seconds:
            return {"checked": 0, "upgraded": 0, "deduplicated": 0, "failed": 0}
        _migration_last_checked[normalized_item_id] = now

    memories = store.get_all_memories(normalized_item_id)
    memories_by_id = {
        str(memory.get("id") or "").strip(): memory
        for memory in memories
        if str(memory.get("id") or "").strip()
    }
    upgraded = 0
    deduplicated = 0
    failed = 0
    for memory in memories:
        memory_id = str(memory.get("id") or "").strip()
        metadata = memory.get("metadata") or {}
        metadata = metadata if isinstance(metadata, dict) else {}
        imported_from = str(metadata.get("imported_from_memory_id") or "").strip()
        original = memories_by_id.get(imported_from)
        if original is not None and memory_id:
            original_type = str(
                (original.get("metadata") or {}).get("memory_type") or "fact"
            ).strip()
            memory_type = str(metadata.get("memory_type") or "fact").strip()
            if (
                original_type == memory_type
                and str(original.get("content") or "").strip()
                == str(memory.get("content") or "").strip()
            ):
                delete_memory = getattr(store, "delete_memory", None)
                if callable(delete_memory) and delete_memory(memory_id):
                    deduplicated += 1
                    continue
        updates = build_legacy_memory_metadata_upgrade(memory)
        if not memory_id or not updates:
            continue
        update_metadata = getattr(store, "update_memory_metadata", None)
        if callable(update_metadata):
            success = bool(update_metadata(memory_id, updates))
        else:
            success = bool(store.update_memory(memory_id, metadata=updates))
        if success:
            upgraded += 1
        else:
            failed += 1

    if upgraded or deduplicated or failed:
        logger.info(
            "[RobotMemoryMigration] item=%s upgraded=%s deduplicated=%s failed=%s",
            normalized_item_id,
            upgraded,
            deduplicated,
            failed,
        )
    return {
        "checked": len(memories),
        "upgraded": upgraded,
        "deduplicated": deduplicated,
        "failed": failed,
    }
