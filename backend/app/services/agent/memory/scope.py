"""Memory/token scope resolution.

Memories and token usage belong to the ItemHandler, not to a single Item:
one handler may drive many items (web item, QQ-bound items, scheduled
tasks), and its learned facts and cost accounting should be shared across
all of them. Storage layers keep a plain scope string; this module is the
single place that decides what that string is — the handler id whenever it
can be resolved, the item id only as a last-resort fallback.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent.agent import Agent

logger = logging.getLogger(__name__)


def resolve_scope(item_id: str = "", agent: "Agent | None" = None) -> str:
    """Resolve the handler scope for memory/token operations.

    Order: the live agent's handler (the agent is per-handler by design),
    then the in-memory item->handler map, then the ItemHandlerItem table.
    Falls back to the raw item id when nothing resolves (legacy callers,
    unlinked items).
    """
    if agent is not None:
        handler_id = str(getattr(agent, "handler_id", "") or "").strip()
        if handler_id:
            return handler_id

    normalized_item_id = str(item_id or "").strip()
    if not normalized_item_id:
        return ""

    try:
        from app.services.agent.agent import item_handler_context

        handler_id = str(
            item_handler_context.get_handler(normalized_item_id) or ""
        ).strip()
        if handler_id:
            return handler_id
    except Exception:
        pass

    try:
        import uuid

        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import ItemHandlerItem

        with Session(engine) as session:
            row = session.exec(
                select(ItemHandlerItem).where(
                    ItemHandlerItem.item_id == uuid.UUID(normalized_item_id)
                )
            ).first()
            if row is not None:
                return str(row.item_handler_id)
    except Exception as exc:
        logger.debug(
            "[MemoryScope] DB handler lookup failed for item=%s: %s",
            normalized_item_id,
            exc,
        )

    return normalized_item_id


def items_for_scope(scope: str) -> list[str]:
    """All item ids belonging to a handler scope (for fan-out queries such
    as per-task token enrichment across the handler's items)."""
    normalized = str(scope or "").strip()
    if not normalized:
        return []
    try:
        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import ItemHandlerItem

        with Session(engine) as session:
            rows = session.exec(
                select(ItemHandlerItem).where(
                    ItemHandlerItem.item_handler_id == normalized
                )
            ).all()
            return [str(row.item_id) for row in rows]
    except Exception:
        return [normalized]
