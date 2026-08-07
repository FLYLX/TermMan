"""Item -> ItemHandler resolution at API/tool boundaries.

Memories and token usage are keyed natively by ItemHandler id. Code paths
that already hold an Agent use ``agent.handler_id`` directly; this module is
only for boundary entry points (HTTP routes, MCP tool arguments) that
receive a raw item id and must find the handler that drives it.

Falls back to the raw item id when the item has no handler association
(legacy/unlinked items), matching the pre-handler behavior.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_handler_id(item_id: str) -> str:
    """Resolve the id of the ItemHandler that drives ``item_id``.

    Order: the in-memory item->handler map (populated when a chat agent is
    prepared), then the ItemHandlerItem table. Falls back to the raw item
    id when nothing resolves.
    """
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


def handler_item_directory(item_id: str) -> tuple[str, list[dict[str, str]]]:
    """Resolve ``item_id`` to its handler plus the handler's item directory.

    Returns ``(handler_id, items)`` where items is a list of
    ``{"item_id", "title"}`` for every item the handler drives, the
    requested item first. Falls back to just the requested item when no
    handler association exists.
    """
    normalized_item_id = str(item_id or "").strip()
    if not normalized_item_id:
        return "", []

    handler_id = resolve_handler_id(normalized_item_id)
    try:
        import uuid

        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import Item, ItemHandlerItem

        with Session(engine) as session:
            current = session.get(Item, uuid.UUID(normalized_item_id))
            current_title = str(current.title) if current is not None else ""
            items: list[dict[str, str]] = [
                {"item_id": normalized_item_id, "title": current_title}
            ]
            if handler_id != normalized_item_id:
                rows = session.exec(
                    select(ItemHandlerItem, Item)
                    .where(ItemHandlerItem.item_handler_id == uuid.UUID(handler_id))
                    .where(Item.id == ItemHandlerItem.item_id)
                ).all()
                for link, item in rows:
                    if str(link.item_id) == normalized_item_id:
                        items[0]["title"] = str(item.title or "")
                    else:
                        items.append(
                            {"item_id": str(link.item_id), "title": str(item.title or "")}
                        )
            return handler_id, items
    except Exception as exc:
        logger.debug(
            "[MemoryScope] item directory lookup failed for item=%s: %s",
            normalized_item_id,
            exc,
        )
        return handler_id, [{"item_id": normalized_item_id, "title": ""}]


def item_titles(item_ids: list[str]) -> dict[str, str]:
    """Batch lookup of item titles for source-tag labeling."""
    wanted = {str(value or "").strip() for value in item_ids}
    wanted.discard("")
    if not wanted:
        return {}
    try:
        import uuid

        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import Item

        uuids = []
        for value in wanted:
            try:
                uuids.append(uuid.UUID(value))
            except ValueError:
                continue
        if not uuids:
            return {}
        with Session(engine) as session:
            rows = session.exec(select(Item).where(Item.id.in_(uuids))).all()
            return {str(row.id): str(row.title or "") for row in rows}
    except Exception:
        return {}

