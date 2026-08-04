"""Restore persisted agent task state after a backend restart."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def restore_agent_state() -> dict[str, int]:
    restored = {"tickets": 0}
    try:
        from app.services.agent.reply_ticket import restore_tickets_from_store

        restored["tickets"] = restore_tickets_from_store()
    except Exception:
        logger.exception("[StateRestore] Failed to restore reply tickets")
    if any(restored.values()):
        logger.info(
            "[StateRestore] Restored tickets=%s",
            restored["tickets"],
        )
    return restored
