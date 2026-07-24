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
# Grace period before declaring a background-job result callback lost.
WAITING_JOB_CALLBACK_GRACE_SECONDS = 60.0
# How often near-duplicate long-term memories are auto-merged per item.
MEMORY_DEDUP_INTERVAL_SECONDS = 1800.0
# Rule-based cluster merge threshold (no LLM involved).
MEMORY_DEDUP_SIMILARITY_THRESHOLD = 0.85

_memory_dedup_last_run: dict[str, float] = {}


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
    if status == "blocked":
        # Legitimate external waits (awaiting a user/event) get a longer leash.
        return float(settings.AGENT_WATCHDOG_BLOCKED_STALE_SECONDS)
    return float(settings.AGENT_WATCHDOG_STALE_SECONDS)


def _closure_notice(workflow: Any) -> str:
    objective = str(workflow.objective or "").strip()[:80] or "未命名任务"
    lines = [f"任务「{objective}」{CLOSE_REASON}。"]
    progress = str(workflow.latest_progress or "").strip()[:120]
    if progress:
        lines.append(f"最后进展：{progress}")
    lines.append("如果还需要继续，重新告诉我一声就行。")
    return "\n".join(lines)


def _get_daemon_connection_for_item(item_id: str):
    """Daemon connection for an item; None when unavailable or unconfigured."""
    try:
        import uuid as uuid_module

        from sqlmodel import Session

        from app.core.db import engine
        from app.models import Item
        from app.services import DaemonConfig, connection_manager

        with Session(engine) as db:
            item = db.get(Item, uuid_module.UUID(str(item_id)))
        if item is None or not item.socket_host or not item.socket_port or not item.api_key:
            return None
        return connection_manager.get_or_create_connection(
            DaemonConfig(item.socket_host, item.socket_port, item.api_key)
        )
    except Exception as exc:
        logger.info(
            "[TaskWatchdog] Daemon connection unavailable for item=%s: %s",
            item_id,
            exc,
        )
        return None


def _list_daemon_job_commands(connection, item_id: str) -> set[str] | None:
    """Commands of jobs the daemon currently tracks for this item.

    Returns None when the daemon is unreachable or unconfigured, so callers
    never treat an outage as "job lost".
    """
    try:
        result = connection.list_jobs_http(item_uuid=str(item_id))
    except Exception as exc:
        logger.info(
            "[TaskWatchdog] Daemon job list unavailable for item=%s: %s",
            item_id,
            exc,
        )
        return None
    if not isinstance(result, dict) or not result.get("success"):
        return None
    jobs = result.get("jobs") or []
    return {
        str(job.get("command") or "").strip()
        for job in jobs
        if isinstance(job, dict) and str(job.get("command") or "").strip()
    }


def _schedule_workflow_continuation(item_id: str, ticket_id: str) -> bool:
    if not ticket_id:
        return False
    try:
        from app.services.agent.session import agent_session_manager

        session = agent_session_manager.get_session(str(item_id))
        if session is None:
            return False
        return session.schedule_task_workflow_continuation(ticket_id)
    except Exception as exc:
        logger.info(
            "[TaskWatchdog] Failed to schedule workflow continuation item=%s: %s",
            item_id,
            exc,
        )
        return False


def _reconcile_waiting_job_workflows(now: datetime, stats: dict[str, int]) -> None:
    """Rescue waiting_job workflows whose background job result never arrived.

    A workflow sits in waiting_job until the daemon job's result is recorded.
    Each running job is polled by its daemon job id first: a result buffered
    on the daemon is recovered and recorded as-is (this covers backend
    restarts, where the poller thread died but the daemon kept the result).
    Only when the daemon no longer knows the job at all is it marked lost,
    and a continuation turn is scheduled so the agent keeps driving the task.
    """
    from app.services.agent.task_workflow import task_workflow_manager

    grace = timedelta(seconds=WAITING_JOB_CALLBACK_GRACE_SECONDS)
    with task_workflow_manager._lock:
        candidates = [
            workflow
            for workflow in task_workflow_manager._workflows.values()
            if workflow.status == "waiting_job"
            and any(
                job.status == "running" and _as_utc(job.started_at) < now - grace
                for job in workflow.jobs
            )
        ]
    connections: dict[str, Any] = {}
    daemon_commands_cache: dict[str, set[str] | None] = {}
    for workflow in candidates:
        ticket_id = workflow.reply_ticket_id or (
            workflow.reply_ticket_ids[-1] if workflow.reply_ticket_ids else ""
        )
        if not ticket_id:
            continue
        if workflow.item_id not in connections:
            connections[workflow.item_id] = _get_daemon_connection_for_item(
                workflow.item_id
            )
        connection = connections[workflow.item_id]
        if connection is None:
            continue
        recovered: list[tuple[Any, dict]] = []
        lost_jobs: list[Any] = []
        for job in workflow.jobs:
            if job.status != "running" or _as_utc(job.started_at) >= now - grace:
                continue
            if job.daemon_job_id:
                try:
                    poll = connection.get_job_result_http(
                        item_uuid=str(workflow.item_id),
                        job_id=job.daemon_job_id,
                    )
                except Exception:
                    continue
                status = str(poll.get("status") or "")
                if poll.get("success") and status == "running":
                    continue
                if (
                    poll.get("success")
                    and status == "finished"
                    and isinstance(poll.get("result"), dict)
                ):
                    recovered.append((job, poll["result"]))
                elif status == "unknown":
                    lost_jobs.append(job)
                # Transient poll errors: skip this pass, retry next tick.
                continue
            # Legacy jobs without a daemon job id: fall back to the
            # command-list disappearance check.
            if workflow.item_id not in daemon_commands_cache:
                daemon_commands_cache[workflow.item_id] = _list_daemon_job_commands(
                    connection,
                    workflow.item_id,
                )
            daemon_commands = daemon_commands_cache[workflow.item_id]
            if daemon_commands is None:
                continue
            if job.command not in daemon_commands:
                lost_jobs.append(job)
        for job, result in recovered:
            logger.info(
                "[TaskWatchdog] Recovered background job result from daemon: workflow=%s command=%r",
                workflow.workflow_id,
                job.command[:120],
            )
            try:
                from app.services.agent.mcp.local_server import local_mcp_server

                result_summary = local_mcp_server._format_job_result(result)
            except Exception:
                result_summary = f"exit_code={result.get('exit_code')}"
            task_workflow_manager.record_job_result(
                ticket_id,
                command=job.command,
                success=bool(result.get("success")),
                result_summary=result_summary,
                daemon_job_id=str(result.get("job_id") or job.daemon_job_id or ""),
                exit_code=result.get("exit_code"),
                workflow_id=workflow.workflow_id,
            )
            stats["reconciled"] += 1
        for job in lost_jobs:
            logger.info(
                "[TaskWatchdog] Background job result lost: workflow=%s command=%r; marking failed and resuming",
                workflow.workflow_id,
                job.command[:120],
            )
            task_workflow_manager.record_job_result(
                ticket_id,
                command=job.command,
                success=False,
                result_summary="后台任务结果丢失：daemon 侧已无此任务，结果回调未送达。",
                workflow_id=workflow.workflow_id,
            )
            stats["reconciled"] += 1
        if recovered or lost_jobs:
            with task_workflow_manager._lock:
                if workflow.status == "waiting_job" and not any(
                    j.status == "running" for j in workflow.jobs
                ):
                    workflow.status = "active"
                    workflow.updated_at = _utcnow()
                    from app.services.agent.task_workflow import _persist_workflow
                    _persist_workflow(workflow)
            stats["reconciled"] += 1


def _item_has_live_execution(item_id: str) -> bool:
    """True when the item has an in-flight turn or interactive terminal work.

    Used to avoid double-driving a workflow while its own turn/session is
    already progressing it.
    """
    try:
        from app.services.agent.session import SessionState, agent_session_manager

        session = agent_session_manager.get_session(str(item_id))
        if session is None:
            return False
        with session.lock:
            if session.state in {
                SessionState.RUNNING,
                SessionState.INTERRUPTING,
                SessionState.COLLECTING,
            }:
                return True
            if session.input_queue.qsize() > 0:
                return True
        try:
            if session.has_pending_command() or session.has_running_terminal_job():
                return True
        except Exception:
            return True
        return False
    except Exception:
        return True


def _resume_stalled_active_workflows(now: datetime, stats: dict[str, int]) -> None:
    """Disabled: workflows are callback-driven, not watchdog-resumed.

    Background job results are delivered through the poller callback path.
    The stale-close timeout (_close_stale_workflow) handles truly abandoned
    workflows by cancelling them.  The old "resume stalled workflows" logic
    caused duplicate turns, repeated QQ reports, and made user abort
    ineffective because the watchdog kept resurrecting cancelled work.
    """


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
    with task_workflow_manager._lock:
        if workflow.status not in {"cancelled", "completed", "failed"}:
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


def _list_all_item_ids() -> list[str]:
    from sqlmodel import Session, select

    from app.core.db import engine
    from app.models import Item

    with Session(engine) as db:
        return [str(item.id) for item in db.exec(select(Item)).all()]


def _dedupe_memory_clusters(now: datetime, stats: dict[str, int]) -> None:
    """Auto-merge near-duplicate long-term memories per item (rule-based, no LLM).

    Runs at most once per MEMORY_DEDUP_INTERVAL_SECONDS per item. Keeps the
    first memory of each near-duplicate cluster and deletes the rest, so
    recalled context does not fill up with repeated facts.
    """
    from app.services.agent.memory.vector_store import vector_store

    now_ts = now.timestamp()
    item_ids = _list_all_item_ids()
    known = set(item_ids)
    for stale_key in set(_memory_dedup_last_run) - known:
        _memory_dedup_last_run.pop(stale_key, None)
    for item_id in item_ids:
        last_run = _memory_dedup_last_run.get(item_id, 0.0)
        if now_ts - last_run < MEMORY_DEDUP_INTERVAL_SECONDS:
            continue
        _memory_dedup_last_run[item_id] = now_ts
        try:
            removed = vector_store.deduplicate_memories(
                item_id, threshold=MEMORY_DEDUP_SIMILARITY_THRESHOLD
            )
            superseded = vector_store.supersede_by_memory_key(item_id)
            removed += superseded
        except Exception as exc:
            logger.info(
                "[TaskWatchdog] Memory dedup failed for item=%s: %s", item_id, exc
            )
            continue
        if removed:
            stats["memories_deduplicated"] += removed
            logger.info(
                "[TaskWatchdog] Merged %s near-duplicate/keyed memories for item=%s",
                removed,
                item_id,
            )


def run_once(now: datetime | None = None) -> dict[str, int]:
    from app.services.agent.task_workflow import (
        WORKFLOW_ACTIVE_STATUSES,
        task_workflow_manager,
    )

    now = now or _utcnow()
    stats = {
        "closed": 0,
        "reported": 0,
        "orphan_tickets_removed": 0,
        "reconciled": 0,
        "resumed": 0,
        "stalled_resumed": 0,
        "dispatch_reaped": 0,
        "memories_deduplicated": 0,
    }
    try:
        _dedupe_memory_clusters(now, stats)
    except Exception:
        logger.exception("[TaskWatchdog] Memory dedup pass failed")
    # Disabled: job results are delivered by the poller thread callback.
    # Watchdog reconciliation caused ghost "result lost" failures and
    # auto-resumed workflows against the callback-driven design.
    try:
        _resume_stalled_active_workflows(now, stats)
    except Exception:
        logger.exception("[TaskWatchdog] Stalled-workflow resume failed")
    try:
        from app.plugins.robot import is_robot_plugin_enabled

        if is_robot_plugin_enabled():
            from app.plugins.robot.service import robot_service

            stats["dispatch_reaped"] = robot_service.reap_stuck_dispatch_jobs()
    except Exception:
        logger.exception("[TaskWatchdog] Dispatch reaper failed")
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
    if stats["closed"] or stats["orphan_tickets_removed"] or stats["memories_deduplicated"]:
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
            "[TaskWatchdog] Started (interval=%ss, idle_resume=%ss, stale=%ss, blocked_stale=%ss, waiting_job_stale=%ss)",
            settings.AGENT_WATCHDOG_INTERVAL_SECONDS,
            settings.AGENT_WATCHDOG_IDLE_RESUME_SECONDS,
            settings.AGENT_WATCHDOG_STALE_SECONDS,
            settings.AGENT_WATCHDOG_BLOCKED_STALE_SECONDS,
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
