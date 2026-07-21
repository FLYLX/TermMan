"""Restore persisted agent task state after a backend restart."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def restore_agent_state() -> dict[str, int]:
    restored = {"workflows": 0, "tickets": 0}
    try:
        from app.services.agent.task_workflow import restore_workflows_from_store

        restored["workflows"] = restore_workflows_from_store()
    except Exception:
        logger.exception("[StateRestore] Failed to restore task workflows")
    try:
        from app.services.agent.reply_ticket import restore_tickets_from_store

        restored["tickets"] = restore_tickets_from_store()
    except Exception:
        logger.exception("[StateRestore] Failed to restore reply tickets")
    if any(restored.values()):
        logger.info(
            "[StateRestore] Restored workflows=%s tickets=%s",
            restored["workflows"],
            restored["tickets"],
        )
    return restored
