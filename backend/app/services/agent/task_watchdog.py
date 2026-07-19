"""Watchdog that closes out stale, non-final task workflows.

Goal: a task is either actively being worked on or reported and closed —
never silently parked. Workflows sitting in a non-final status without
updates past a timeout get cancelled and, when they have a live reply
ticket, a closure notice is delivered through the ticket's destinations.
Orphan reply tickets (no linked workflow, or inactive tickets past their
TTL) are removed as well.

All work is best-effort: individual failures are logged and never stop the
scan.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

CLOSE_REASON = "任务长时间没有进展，已自动关闭"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        # Naive datetimes in tickets are local time (datetime.now()).
        return value.astimezone(timezone.utc)
    return value


def _stale_timeout_seconds(status: str) -> float:
    if status == "waiting_job":
        return float(settings.AGENT_WATCHDOG_WAITING_JOB_STALE_SECONDS)
    return float(settings.AGENT_WATCHDOG_STALE_SECONDS)


def _closure_notice(workflow: Any) -> str:
    objective = str(workflow.objective or "").strip()[:80] or "未命名任务"
    lines = [f"任务「{objective}」{CLOSE_REASON}。"]
    progress = str(workflow.latest_progress or "").strip()[:120]
    if progress:
        lines.append(f"最后进展：{progress}")
    lines.append("如果还需要继续，重新告诉我一声就行。")
    return "\n".join(lines)


def _close_stale_workflow(workflow: Any, stats: dict[str, int], *, now: datetime) -> None:
    from app.services.agent import task_workflow as workflow_module
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    ticket_id = workflow.reply_ticket_id or (
        workflow.reply_ticket_ids[-1] if workflow.reply_ticket_ids else ""
    )
    logger.info(
        "[TaskWatchdog] Closing stale workflow=%s item=%s status=%s updated_at=%s",
        workflow.workflow_id,
        workflow.item_id,
        workflow.status,
        workflow.updated_at,
    )
    if ticket_id:
        task_workflow_manager.update(
            ticket_id,
            action="cancel",
            note=f"Stale {workflow.status} workflow closed by watchdog.",
        )
    else:
        with task_workflow_manager._lock:
            workflow.status = "cancelled"
            workflow.blocker = "Closed by watchdog: stale non-final workflow."
            workflow.updated_at = now
        workflow_module._persist_workflow(workflow)
    stats["closed"] += 1

    if not ticket_id:
        return
    ticket = reply_ticket_manager.get(ticket_id)
    if ticket is None:
        return
    try:
        delivered = reply_ticket_manager.deliver(ticket_id, _closure_notice(workflow))
    except Exception as exc:
        logger.warning(
            "[TaskWatchdog] Closure notice failed for workflow=%s: %s",
            workflow.workflow_id,
            exc,
        )
        return
    if delivered:
        stats["reported"] += 1
    else:
        logger.info(
            "[TaskWatchdog] Closure notice not delivered for workflow=%s",
            workflow.workflow_id,
        )


def _remove_orphan_tickets(now: datetime, stats: dict[str, int]) -> None:
    from app.services.agent.reply_ticket import TICKET_TTL, reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    inactive_cutoff = now - TICKET_TTL
    with reply_ticket_manager._lock:
        tickets = list(reply_ticket_manager._tickets.values())
    for ticket in tickets:
        updated_at = _as_utc(ticket.updated_at)
        workflow = task_workflow_manager.get_by_ticket(ticket.ticket_id)
        if workflow is not None or updated_at >= inactive_cutoff:
            continue
        with reply_ticket_manager._lock:
            reply_ticket_manager._tickets.pop(ticket.ticket_id, None)
            reply_ticket_manager._remove_aliases_for_locked(ticket.ticket_id)
        from app.services.agent.reply_ticket import (
            _delete_persisted_tickets,
            _persist_aliases,
        )

        _delete_persisted_tickets([ticket.ticket_id])
        _persist_aliases(reply_ticket_manager._ticket_aliases)
        stats["orphan_tickets_removed"] += 1


def run_once(now: datetime | None = None) -> dict[str, int]:
    from app.services.agent.task_workflow import (
        WORKFLOW_ACTIVE_STATUSES,
        task_workflow_manager,
    )

    now = now or _utcnow()
    stats = {"closed": 0, "reported": 0, "orphan_tickets_removed": 0}
    with task_workflow_manager._lock:
        candidates = [
            workflow
            for workflow in task_workflow_manager._workflows.values()
            if workflow.status in WORKFLOW_ACTIVE_STATUSES
            and _as_utc(workflow.updated_at)
            < now - timedelta(seconds=_stale_timeout_seconds(workflow.status))
        ]
    for workflow in candidates:
        try:
            _close_stale_workflow(workflow, stats, now=now)
        except Exception:
            logger.exception(
                "[TaskWatchdog] Failed to close stale workflow=%s",
                workflow.workflow_id,
            )
    try:
        _remove_orphan_tickets(now, stats)
    except Exception:
        logger.exception("[TaskWatchdog] Failed to remove orphan tickets")
    if stats["closed"] or stats["orphan_tickets_removed"]:
        logger.info("[TaskWatchdog] Pass finished: %s", stats)
    return stats


class AgentTaskWatchdog:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="termman-agent-task-watchdog",
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "[TaskWatchdog] Started (interval=%ss, stale=%ss, waiting_job_stale=%ss)",
            settings.AGENT_WATCHDOG_INTERVAL_SECONDS,
            settings.AGENT_WATCHDOG_STALE_SECONDS,
            settings.AGENT_WATCHDOG_WAITING_JOB_STALE_SECONDS,
        )

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    def _loop(self) -> None:
        interval = max(5.0, float(settings.AGENT_WATCHDOG_INTERVAL_SECONDS))
        while not self._stop_event.wait(interval):
            try:
                run_once()
            except Exception:
                logger.exception("[TaskWatchdog] Pass failed")


agent_task_watchdog = AgentTaskWatchdog()
