"""One-shot migration: rewrite memory/token scopes from item ids to handler ids.

Memories and token usage used to be keyed by item id. They now belong to the
ItemHandler (one handler's items share the pool). On startup we rewrite every
stored scope that maps to a handler through ItemHandlerItem. Rows whose item
has no handler association are left untouched (legacy/unlinked data).

Physical fields stay named `item_id` (Chroma metadata, FTS column, token
table column); only their VALUES change to the handler id.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MIGRATION_KV_KEY = "handler_scope_migration_v1"


def _item_to_handler_map() -> dict[str, str]:
    from sqlmodel import Session, select

    from app.core.db import engine
    from app.models import ItemHandlerItem

    mapping: dict[str, str] = {}
    with Session(engine) as session:
        for row in session.exec(select(ItemHandlerItem)).all():
            mapping[str(row.item_id)] = str(row.item_handler_id)
    return mapping


def _migrate_token_usage(mapping: dict[str, str]) -> int:
    if not mapping:
        return 0
    from sqlalchemy import text

    from app.core.db import engine

    migrated = 0
    try:
        with engine.begin() as conn:
            for item_id, handler_id in mapping.items():
                result = conn.execute(
                    text(
                        "UPDATE token_usage_record SET item_id = :handler "
                        "WHERE item_id = :item"
                    ),
                    {"handler": handler_id, "item": item_id},
                )
                migrated += result.rowcount or 0
    except Exception as exc:
        logger.warning("[ScopeMigration] token usage migration failed: %s", exc)
    return migrated


def _migrate_memory_store(mapping: dict[str, str]) -> int:
    if not mapping:
        return 0
    migrated = 0
    try:
        from app.services.agent.memory.vector_store import vector_store

        for memory in vector_store.get_all_memories(""):
            metadata = memory.get("metadata") or {}
            old_scope = str(metadata.get("item_id") or "").strip()
            new_scope = mapping.get(old_scope)
            if not old_scope or not new_scope or new_scope == old_scope:
                continue
            memory_id = str(memory.get("id") or "")
            if not memory_id:
                continue
            try:
                vector_store.update_memory(
                    memory_id,
                    metadata={**metadata, "item_id": new_scope},
                )
                migrated += 1
            except Exception as exc:
                logger.debug(
                    "[ScopeMigration] memory %s update failed: %s", memory_id, exc
                )
    except Exception as exc:
        logger.warning("[ScopeMigration] memory store scan failed: %s", exc)
    return migrated


def run_handler_scope_migration() -> dict[str, int]:
    """Idempotent: runs once, records completion in the state KV store."""
    try:
        from app.services.agent import state_store

        if state_store.load_kv(_MIGRATION_KV_KEY).get("done"):
            return {"skipped": 1}
    except Exception:
        return {"skipped": 1}

    mapping = _item_to_handler_map()
    result = {
        "tokens": _migrate_token_usage(mapping),
        "memories": _migrate_memory_store(mapping),
    }
    try:
        from app.services.agent import state_store

        state_store.save_kv(_MIGRATION_KV_KEY, {"done": True, **result})
    except Exception:
        pass
    if result["tokens"] or result["memories"]:
        logger.info(
            "[ScopeMigration] migrated %s token rows, %s memories to handler scope",
            result["tokens"],
            result["memories"],
        )
    return result
