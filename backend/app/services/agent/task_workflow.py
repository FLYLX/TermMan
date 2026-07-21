from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

WORKFLOW_ACTIVE_STATUSES = {
    "active",
    "waiting_job",
    "verifying",
    "blocked",
    "ready_to_report",
    "reporting",
}
WORKFLOW_FINAL_STATUSES = {"completed", "cancelled", "failed"}
STEP_ACTIVE_STATUSES = {"running", "waiting", "failed"}
MAX_WORKFLOWS_PER_ITEM = 8
COMPLETED_RETENTION = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


VERIFICATION_STEP_TITLE_RE = re.compile(
    r"(验证|检查|确认|核实|verify|check|confirm)",
    re.IGNORECASE,
)


def _is_verification_step(step: WorkflowStep) -> bool:
    return bool(VERIFICATION_STEP_TITLE_RE.search(str(step.title or "")))


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class WorkflowStep:
    step_id: str
    title: str
    status: str = "pending"
    attempts: int = 0
    note: str = ""
    evidence: str = ""
    last_error: str = ""
    recovery: bool = False


@dataclass
class WorkflowJob:
    workflow_job_id: str
    command: str
    step_id: str = ""
    workflow_id: str = ""
    status: str = "running"
    daemon_job_id: str = ""
    success: bool | None = None
    exit_code: int | None = None
    result_summary: str = ""
    started_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None


@dataclass
class TaskWorkflow:
    workflow_id: str
    item_id: str
    handler_id: str
    reply_ticket_id: str
    objective: str
    source_type: str
    source_label: str
    steps: list[WorkflowStep]
    report_policy: str = "normal"
    requester: str = ""
    queue_status: str = "working"
    awaiting_kind: str = ""
    awaiting_key: str = ""
    status: str = "active"
    current_step_index: int = 0
    latest_progress: str = ""
    latest_user_instruction: str = ""
    blocker: str = ""
    last_tool_name: str = ""
    last_command: str = ""
    auto_resume_attempts: int = 0
    jobs: list[WorkflowJob] = field(default_factory=list)
    reply_ticket_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    delivered_at: datetime | None = None

    def current_step(self) -> WorkflowStep | None:
        if not self.steps:
            return None
        index = max(0, min(self.current_step_index, len(self.steps) - 1))
        return self.steps[index]

    def find_step_by_id(self, step_id: str) -> WorkflowStep | None:
        if not step_id:
            return None
        return next(
            (step for step in self.steps if step.step_id == step_id), None
        )

    def resolve_step_for_job(self, job: WorkflowJob) -> WorkflowStep | None:
        return self.find_step_by_id(job.step_id) or self.current_step()


def workflow_to_payload(workflow: TaskWorkflow) -> dict[str, Any]:
    current = workflow.current_step()
    return {
        "workflow_id": workflow.workflow_id,
        "item_id": workflow.item_id,
        "handler_id": workflow.handler_id,
        "reply_ticket_id": workflow.reply_ticket_id,
        "reply_ticket_ids": list(workflow.reply_ticket_ids),
        "objective": workflow.objective,
        "source_type": workflow.source_type,
        "source_label": workflow.source_label,
        "report_policy": workflow.report_policy,
        "requester": workflow.requester,
        "queue_status": workflow.queue_status,
        "awaiting_kind": workflow.awaiting_kind,
        "awaiting_key": workflow.awaiting_key,
        "status": workflow.status,
        "current_step_index": workflow.current_step_index,
        "current_step": current.title if current else "",
        "latest_progress": workflow.latest_progress,
        "latest_user_instruction": workflow.latest_user_instruction,
        "blocker": workflow.blocker,
        "last_tool_name": workflow.last_tool_name,
        "last_command": workflow.last_command,
        "auto_resume_attempts": workflow.auto_resume_attempts,
        "created_at": _iso(workflow.created_at),
        "updated_at": _iso(workflow.updated_at),
        "delivered_at": _iso(workflow.delivered_at),
        "steps": [asdict(step) for step in workflow.steps],
        "jobs": [
            {
                **asdict(job),
                "started_at": _iso(job.started_at),
                "completed_at": _iso(job.completed_at),
            }
            for job in workflow.jobs
        ],
    }


def _filtered_kwargs(cls: Any, data: Any) -> dict[str, Any]:
    allowed = {field_info.name for field_info in dataclass_fields(cls)}
    return {
        key: value for key, value in dict(data or {}).items() if key in allowed
    }


def workflow_from_payload(payload: dict[str, Any]) -> TaskWorkflow:
    steps = [
        WorkflowStep(**_filtered_kwargs(WorkflowStep, step_data))
        for step_data in payload.get("steps") or []
    ]
    jobs: list[WorkflowJob] = []
    for job_data in payload.get("jobs") or []:
        job_kwargs = _filtered_kwargs(WorkflowJob, job_data)
        job_kwargs["started_at"] = _parse_dt(job_kwargs.get("started_at")) or _utcnow()
        job_kwargs["completed_at"] = _parse_dt(job_kwargs.get("completed_at"))
        jobs.append(WorkflowJob(**job_kwargs))
    kwargs = _filtered_kwargs(TaskWorkflow, payload)
    kwargs["steps"] = steps
    kwargs["jobs"] = jobs
    kwargs["created_at"] = _parse_dt(kwargs.get("created_at")) or _utcnow()
    kwargs["updated_at"] = _parse_dt(kwargs.get("updated_at")) or _utcnow()
    kwargs["delivered_at"] = _parse_dt(kwargs.get("delivered_at"))
    return TaskWorkflow(**kwargs)


def _persist_workflow(workflow: TaskWorkflow | None) -> None:
    if workflow is None:
        return
    try:
        from app.services.agent import state_store

        state_store.save_workflow(workflow_to_payload(workflow))
    except Exception as exc:
        logger.debug("[TaskWorkflow] Persist workflow failed: %s", exc)


def _delete_persisted_workflows(workflow_ids: list[str]) -> None:
    if not workflow_ids:
        return
    try:
        from app.services.agent import state_store

        for workflow_id in workflow_ids:
            state_store.delete_workflow(workflow_id)
    except Exception as exc:
        logger.debug("[TaskWorkflow] Delete persisted workflows failed: %s", exc)


def normalize_restored_workflow(workflow: TaskWorkflow) -> None:
    interrupted = False
    for job in workflow.jobs:
        if job.status == "running":
            job.status = "failed"
            job.success = False
            job.result_summary = (
                f"{job.result_summary} Interrupted by backend restart.".strip()
            )
            job.completed_at = _utcnow()
            interrupted = True
    if workflow.status == "waiting_job":
        workflow.status = "active"
        interrupted = True
    elif workflow.status == "reporting":
        workflow.status = "ready_to_report"
    if interrupted:
        note = "Backend restarted; execution was interrupted and can be resumed."
        workflow.latest_progress = f"{workflow.latest_progress} {note}".strip()


def restore_workflows_from_store() -> int:
    try:
        from app.services.agent import state_store
    except Exception:
        return 0
    restored = 0
    with task_workflow_manager._lock:
        for payload in state_store.load_workflows():
            try:
                workflow = workflow_from_payload(payload)
            except Exception:
                continue
            if workflow.status in WORKFLOW_FINAL_STATUSES:
                _delete_persisted_workflows([workflow.workflow_id])
                continue
            normalize_restored_workflow(workflow)
            task_workflow_manager._workflows[workflow.workflow_id] = workflow
            for ticket_id in workflow.reply_ticket_ids:
                task_workflow_manager._ticket_to_workflow[ticket_id] = (
                    workflow.workflow_id
                )
            if workflow.reply_ticket_id:
                task_workflow_manager._ticket_to_workflow[workflow.reply_ticket_id] = (
                    workflow.workflow_id
                )
            restored += 1
    return restored


class TaskWorkflowManager:
    def __init__(self) -> None:
        self._workflows: dict[str, TaskWorkflow] = {}
        self._ticket_to_workflow: dict[str, str] = {}
        self._lock = threading.RLock()

    def _remove_workflow_mappings_locked(self, workflow_id: str) -> None:
        stale_ticket_ids = [
            ticket_id
            for ticket_id, mapped_workflow_id in self._ticket_to_workflow.items()
            if mapped_workflow_id == workflow_id
        ]
        for ticket_id in stale_ticket_ids:
            self._ticket_to_workflow.pop(ticket_id, None)

    def _prune_locked(self, now: datetime) -> None:
        cutoff = now - COMPLETED_RETENTION
        stale_ids = [
            workflow_id
            for workflow_id, workflow in self._workflows.items()
            if workflow.status in WORKFLOW_FINAL_STATUSES
            and workflow.updated_at < cutoff
        ]
        for workflow_id in stale_ids:
            workflow = self._workflows.pop(workflow_id, None)
            if workflow:
                self._remove_workflow_mappings_locked(workflow.workflow_id)
        _delete_persisted_workflows(stale_ids)

        by_item: dict[str, list[TaskWorkflow]] = {}
        for workflow in self._workflows.values():
            by_item.setdefault(workflow.item_id, []).append(workflow)
        for workflows in by_item.values():
            if len(workflows) <= MAX_WORKFLOWS_PER_ITEM:
                continue
            removable = sorted(
                (
                    workflow
                    for workflow in workflows
                    if workflow.status in WORKFLOW_FINAL_STATUSES
                ),
                key=lambda workflow: workflow.updated_at,
            )
            for workflow in removable[: len(workflows) - MAX_WORKFLOWS_PER_ITEM]:
                self._workflows.pop(workflow.workflow_id, None)
                self._remove_workflow_mappings_locked(workflow.workflow_id)
            _delete_persisted_workflows(
                [
                    workflow.workflow_id
                    for workflow in removable[: len(workflows) - MAX_WORKFLOWS_PER_ITEM]
                ]
            )

    def reset(self) -> None:
        with self._lock:
            _delete_persisted_workflows(list(self._workflows.keys()))
            self._workflows.clear()
            self._ticket_to_workflow.clear()

    def create(
        self,
        *,
        item_id: str,
        handler_id: str,
        reply_ticket_id: str,
        objective: str,
        source_type: str,
        source_label: str,
        step_titles: list[str],
        workflow_id: str | None = None,
    ) -> TaskWorkflow:
        now = _utcnow()
        titles = [str(title or "").strip()[:180] for title in step_titles]
        titles = [title for title in titles if title]
        if not titles:
            titles = ["Execute the requested operation", "Verify the final result"]
        steps = [
            WorkflowStep(
                step_id=uuid.uuid4().hex[:12],
                title=title,
                status="running" if index == 0 else "pending",
            )
            for index, title in enumerate(titles)
        ]
        workflow = TaskWorkflow(
            workflow_id=workflow_id or str(uuid.uuid4()),
            item_id=str(item_id),
            handler_id=str(handler_id),
            reply_ticket_id=str(reply_ticket_id),
            objective=str(objective or "").strip()[:1000],
            source_type=str(source_type or "web"),
            source_label=str(source_label or ""),
            steps=steps,
            reply_ticket_ids=[str(reply_ticket_id)] if reply_ticket_id else [],
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._prune_locked(now)
            self._workflows[workflow.workflow_id] = workflow
            if workflow.reply_ticket_id:
                self._ticket_to_workflow[workflow.reply_ticket_id] = (
                    workflow.workflow_id
                )
        _persist_workflow(workflow)
        return workflow

    def get(self, workflow_id: str) -> TaskWorkflow | None:
        with self._lock:
            return self._workflows.get(str(workflow_id or ""))

    def get_by_ticket(self, ticket_id: str) -> TaskWorkflow | None:
        with self._lock:
            workflow_id = self._ticket_to_workflow.get(str(ticket_id or ""))
            return self._workflows.get(workflow_id or "")

    def attach_ticket(self, workflow_id: str, ticket_id: str) -> bool:
        with self._lock:
            workflow = self._workflows.get(str(workflow_id or ""))
            if not workflow:
                return False
            normalized_ticket_id = str(ticket_id or "")
            if normalized_ticket_id and normalized_ticket_id not in workflow.reply_ticket_ids:
                workflow.reply_ticket_ids.append(normalized_ticket_id)
            workflow.reply_ticket_id = normalized_ticket_id
            workflow.auto_resume_attempts = 0
            workflow.updated_at = _utcnow()
            if normalized_ticket_id:
                self._ticket_to_workflow[normalized_ticket_id] = workflow.workflow_id
            _persist_workflow(workflow)
            return True

    def ticket_ids(self, workflow_id: str) -> list[str]:
        with self._lock:
            workflow = self._workflows.get(str(workflow_id or ""))
            if not workflow:
                return []
            return list(workflow.reply_ticket_ids)

    def detach_ticket(self, ticket_id: str) -> bool:
        normalized_ticket_id = str(ticket_id or "")
        with self._lock:
            workflow_id = self._ticket_to_workflow.get(normalized_ticket_id)
            workflow = self._workflows.get(workflow_id or "")
            if not workflow:
                return False
            workflow.reply_ticket_ids = [
                candidate
                for candidate in workflow.reply_ticket_ids
                if candidate != normalized_ticket_id
            ]
            if workflow.reply_ticket_id == normalized_ticket_id:
                workflow.reply_ticket_id = (
                    workflow.reply_ticket_ids[-1] if workflow.reply_ticket_ids else ""
                )
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def replace_ticket(self, old_ticket_id: str, new_ticket_id: str) -> bool:
        old_id = str(old_ticket_id or "")
        new_id = str(new_ticket_id or "")
        if not old_id or not new_id:
            return False
        with self._lock:
            workflow_id = self._ticket_to_workflow.get(old_id)
            workflow = self._workflows.get(workflow_id or "")
            if not workflow:
                return False
            workflow.reply_ticket_ids = [
                candidate
                for candidate in workflow.reply_ticket_ids
                if candidate != old_id
            ]
            if new_id not in workflow.reply_ticket_ids:
                workflow.reply_ticket_ids.append(new_id)
            self._ticket_to_workflow[old_id] = workflow.workflow_id
            self._ticket_to_workflow[new_id] = workflow.workflow_id
            workflow.reply_ticket_id = new_id
            workflow.auto_resume_attempts = 0
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def update_queue_metadata(
        self,
        ticket_id: str,
        *,
        requester: str = "",
        status: str = "",
        awaiting_kind: str = "",
        awaiting_key: str = "",
    ) -> bool:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return False
            if requester:
                workflow.requester = str(requester)[:200]
            if status:
                workflow.queue_status = str(status)[:32]
            if awaiting_kind:
                workflow.awaiting_kind = str(awaiting_kind)[:64]
            if awaiting_key:
                workflow.awaiting_key = str(awaiting_key)[:200]
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def set_report_policy(self, ticket_id: str, policy: str) -> bool:
        normalized = str(policy or "normal").strip().lower()
        if normalized not in {"normal", "final_only"}:
            return False
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return False
            workflow.report_policy = normalized
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def should_suppress_intermediate_delivery(self, ticket_id: str) -> bool:
        workflow = self.get_by_ticket(ticket_id)
        if not workflow or workflow.report_policy != "final_only":
            return False
        can_finalize, _ = self.can_finalize(ticket_id)
        return not can_finalize

    def claim_auto_resume(self, ticket_id: str, *, max_attempts: int = 2) -> bool:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow or workflow.status not in {"active", "verifying"}:
                return False
            if workflow.delivered_at is not None:
                return False
            if any(job.status == "running" for job in workflow.jobs):
                return False
            if workflow.auto_resume_attempts >= max(1, int(max_attempts)):
                return False
            workflow.auto_resume_attempts += 1
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def reset_auto_resume(self, ticket_id: str) -> None:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return
            workflow.auto_resume_attempts = 0
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)

    def mark_waiting(
        self,
        ticket_id: str,
        *,
        awaiting_kind: str,
        awaiting_key: str = "",
        note: str = "",
    ) -> bool:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return False
            step = workflow.current_step()
            if step and step.status not in {"completed", "cancelled"}:
                step.status = "waiting"
                if note:
                    step.note = str(note)[:2000]
            workflow.status = "blocked"
            workflow.queue_status = "waiting"
            workflow.awaiting_kind = str(awaiting_kind or "external_input")[:64]
            workflow.awaiting_key = str(awaiting_key or "")[:200]
            workflow.blocker = str(note or "Waiting for an external prerequisite.")[:2000]
            workflow.latest_progress = workflow.blocker
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def find_resumable(
        self,
        *,
        item_id: str,
        source_type: str,
        source_label: str,
    ) -> TaskWorkflow | None:
        candidates = self.list_resumable(
            item_id=item_id,
            source_type=source_type,
            source_label=source_label,
        )
        return candidates[0] if candidates else None

    def list_resumable(
        self,
        *,
        item_id: str,
        source_type: str = "",
        source_label: str = "",
    ) -> list[TaskWorkflow]:
        with self._lock:
            candidates = [
                workflow
                for workflow in self._workflows.values()
                if workflow.item_id == str(item_id)
                and (not source_type or workflow.source_type == str(source_type))
                and (not source_label or workflow.source_label == str(source_label))
                and workflow.status in {"blocked", "active", "waiting_job", "verifying"}
            ]
        candidates.sort(key=lambda workflow: workflow.updated_at, reverse=True)
        return candidates

    def record_user_instruction(self, ticket_id: str, instruction: str) -> bool:
        normalized = str(instruction or "").strip()[:1000]
        if not normalized:
            return False
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return False
            workflow.latest_user_instruction = normalized
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def record_tool_call(
        self,
        ticket_id: str,
        *,
        tool_name: str,
        command: str = "",
    ) -> None:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return
            step = workflow.current_step()
            if step:
                step.status = "running"
                step.attempts += 1
                step.last_error = ""
            workflow.status = (
                "waiting_job"
                if any(candidate.status == "running" for candidate in workflow.jobs)
                else "active"
            )
            workflow.blocker = ""
            workflow.last_tool_name = str(tool_name or "")
            workflow.last_command = str(command or "").strip()[:1000]
            workflow.latest_progress = (
                f"Started {tool_name}: {workflow.last_command}"
                if workflow.last_command
                else f"Started {tool_name}"
            )
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)

    def mark_job_started(self, ticket_id: str, *, command: str) -> str:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return ""
            step = workflow.current_step()
            job = WorkflowJob(
                workflow_job_id=uuid.uuid4().hex[:12],
                command=str(command or "").strip()[:2000],
                step_id=step.step_id if step else "",
                workflow_id=workflow.workflow_id,
            )
            workflow.jobs.append(job)
            workflow.jobs = workflow.jobs[-12:]
            workflow.status = "waiting_job"
            workflow.latest_progress = f"Background job running: {job.command}"
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return job.workflow_job_id

    def attach_daemon_job_id(
        self,
        ticket_id: str,
        *,
        command: str,
        daemon_job_id: str,
        workflow_id: str = "",
    ) -> bool:
        """Record the daemon-side job id on the running job entry.

        Stored at job start so that after a backend restart the watchdog can
        recover the real result by polling the daemon instead of declaring
        the job lost.
        """
        normalized_command = str(command or "").strip()[:2000]
        daemon_job_id = str(daemon_job_id or "").strip()
        if not normalized_command or not daemon_job_id:
            return False
        with self._lock:
            workflow = (
                self._workflows.get(str(workflow_id or ""))
                if workflow_id
                else None
            ) or self.get_by_ticket(ticket_id)
            if not workflow:
                return False
            job = next(
                (
                    candidate
                    for candidate in reversed(workflow.jobs)
                    if candidate.status == "running"
                    and candidate.command == normalized_command
                ),
                None,
            )
            if job is None:
                return False
            job.daemon_job_id = daemon_job_id
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def record_tool_result(
        self,
        ticket_id: str,
        *,
        tool_name: str,
        success: bool,
        result_summary: str,
    ) -> None:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return
            summary = str(result_summary or "").strip()[-2000:]
            step = workflow.current_step()
            if step:
                if success:
                    step.status = "running"
                    step.evidence = summary
                    step.last_error = ""
                else:
                    step.status = "failed"
                    step.last_error = summary
            workflow.status = (
                "waiting_job"
                if any(candidate.status == "running" for candidate in workflow.jobs)
                else "active"
            )
            workflow.latest_progress = (
                f"{tool_name} {'succeeded' if success else 'failed'}: {summary}"
            ).strip()[:3000]
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)

    def record_job_result(
        self,
        ticket_id: str,
        *,
        command: str,
        success: bool,
        result_summary: str,
        daemon_job_id: str = "",
        exit_code: int | None = None,
        workflow_id: str = "",
    ) -> None:
        with self._lock:
            workflow = (
                self._workflows.get(str(workflow_id or ""))
                if workflow_id
                else None
            ) or self.get_by_ticket(ticket_id)
            if not workflow:
                return
            normalized_command = str(command or "").strip()
            job = next(
                (
                    candidate
                    for candidate in reversed(workflow.jobs)
                    if candidate.status == "running"
                    and candidate.command == normalized_command
                ),
                None,
            )
            if job is None:
                fallback_step = workflow.current_step()
                job = WorkflowJob(
                    workflow_job_id=uuid.uuid4().hex[:12],
                    command=normalized_command,
                    step_id=fallback_step.step_id if fallback_step else "",
                    workflow_id=workflow.workflow_id,
                )
                workflow.jobs.append(job)
            job.status = "succeeded" if success else "failed"
            job.success = bool(success)
            job.daemon_job_id = str(daemon_job_id or "")
            job.exit_code = exit_code
            job.result_summary = str(result_summary or "").strip()[-2000:]
            job.completed_at = _utcnow()
            step = workflow.resolve_step_for_job(job)
            if step and not success:
                step.status = "failed"
                step.last_error = job.result_summary
            elif step:
                step.status = "running"
                step.evidence = job.result_summary
            workflow.status = (
                "waiting_job"
                if any(candidate.status == "running" for candidate in workflow.jobs)
                else "active"
            )
            workflow.blocker = ""
            workflow.latest_progress = (
                f"Background job {'succeeded' if success else 'failed'}: "
                f"{normalized_command}. {job.result_summary}"
            ).strip()[:3000]
            workflow.auto_resume_attempts = 0
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)

    def update(
        self,
        ticket_id: str,
        *,
        action: str,
        note: str = "",
        step_index: int | None = None,
        title: str = "",
    ) -> tuple[bool, str]:
        normalized_action = str(action or "").strip().lower()
        note = str(note or "").strip()[:2000]
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return False, "No active task workflow is linked to this reply ticket."
            step = workflow.current_step()

            if normalized_action == "record_progress":
                workflow.latest_progress = note or workflow.latest_progress
                if step and note:
                    step.note = note
                    if step.status == "failed":
                        step.status = "running"
                workflow.status = "active"
                workflow.blocker = ""
            elif normalized_action == "complete_current_step":
                if step and _is_verification_step(step) and step.attempts <= 0:
                    return (
                        False,
                        "Verification steps require fresh evidence from this run: call a "
                        "check/verify tool now and use its real output as evidence before "
                        "completing this step.",
                    )
                if step:
                    step.status = "completed"
                    step.evidence = note or step.evidence
                    step.last_error = ""
                next_index = workflow.current_step_index + 1
                if next_index < len(workflow.steps):
                    workflow.current_step_index = next_index
                    workflow.steps[next_index].status = "running"
                    workflow.status = "active"
                else:
                    workflow.status = "ready_to_report"
                workflow.latest_progress = note or "Current step completed."
                workflow.blocker = ""
            elif normalized_action == "set_current_step":
                if step_index is None or not (0 <= step_index < len(workflow.steps)):
                    return False, "step_index is out of range."
                workflow.current_step_index = step_index
                workflow.steps[step_index].status = "running"
                workflow.status = "active"
                workflow.blocker = ""
                workflow.latest_progress = note or workflow.latest_progress
            elif normalized_action == "insert_recovery_step":
                recovery_title = str(title or note or "Recovery step").strip()[:180]
                existing_recovery = next(
                    (
                        candidate
                        for candidate in workflow.steps
                        if candidate.title == recovery_title
                        and candidate.status not in {"completed", "cancelled"}
                    ),
                    None,
                )
                if existing_recovery is not None:
                    # Same recovery already exists: resume it instead of
                    # bloating the plan with duplicate recovery steps.
                    if step and step is not existing_recovery:
                        step.status = "waiting"
                    workflow.current_step_index = workflow.steps.index(existing_recovery)
                    existing_recovery.status = "running"
                    workflow.status = "active"
                    workflow.blocker = ""
                    workflow.latest_progress = f"Recovery step resumed: {recovery_title}"
                else:
                    if step:
                        step.status = "waiting"
                    recovery = WorkflowStep(
                        step_id=uuid.uuid4().hex[:12],
                        title=recovery_title,
                        status="running",
                        note=note,
                        recovery=True,
                    )
                    workflow.steps.insert(workflow.current_step_index, recovery)
                    workflow.status = "active"
                    workflow.blocker = ""
                    workflow.latest_progress = f"Recovery step added: {recovery_title}"
            elif normalized_action == "mark_ready_to_report":
                incomplete = [
                    task
                    for task in workflow.steps
                    if task.status not in {"completed", "cancelled"}
                ]
                if incomplete:
                    return (
                        False,
                        "Cannot report completion while workflow steps remain incomplete: "
                        + ", ".join(task.title for task in incomplete[:3]),
                    )
                workflow.status = "ready_to_report"
                workflow.latest_progress = (
                    note or "Objective verified and ready to report."
                )
                workflow.blocker = ""
            elif normalized_action == "mark_blocked":
                if not note:
                    return False, "A blocker reason is required."
                workflow.status = "blocked"
                workflow.blocker = note
                workflow.latest_progress = note
                if step:
                    step.status = "waiting"
                    step.note = note
            elif normalized_action == "resume":
                workflow.status = "active"
                workflow.queue_status = "working"
                workflow.awaiting_kind = ""
                workflow.awaiting_key = ""
                workflow.blocker = ""
                if step:
                    step.status = "running"
                workflow.latest_progress = note or "Workflow resumed."
            elif normalized_action == "cancel":
                workflow.status = "cancelled"
                workflow.blocker = note
                if step:
                    step.status = "cancelled"
            else:
                return False, f"Unsupported workflow action: {normalized_action}"

            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True, workflow.status

    def complete_final_step_on_delivery(self, ticket_id: str) -> bool:
        """Auto-complete when a delivery lands on the workflow's last step.

        A user-facing conclusion delivered while the workflow is on its final
        step IS the completion report: mark the step completed and move the
        workflow to ready_to_report so delivery closes the task instead of
        leaving it stuck at N/N active forever.
        """
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow or workflow.status not in {"active", "verifying"}:
                return False
            if not workflow.steps or workflow.current_step_index != len(workflow.steps) - 1:
                return False
            step = workflow.current_step()
            if step is None or step.status in {"completed", "cancelled"}:
                return False
            if _is_verification_step(step) and step.attempts <= 0:
                # A verbal "verified" claim without a fresh tool run is not
                # evidence; keep the workflow active so the check gets run.
                return False
            step.status = "completed"
            step.evidence = step.evidence or "Final delivery confirmed."
            workflow.status = "ready_to_report"
            workflow.blocker = ""
            workflow.latest_progress = (
                workflow.latest_progress or "Final step completed via delivery."
            )
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            return True

    def complete_last_step_workflow_on_delivery(self, item_id: str) -> bool:
        """Close the most recent last-step workflow of an item after a delivery.

        The completion report may go out on a ticket that was never attached
        to the workflow (a follow-up question opening a fresh ticket). When a
        delivery succeeds while such a workflow sits on its final step, the
        delivered conclusion IS its report: finish the step and close it.
        """
        with self._lock:
            candidates = [
                workflow
                for workflow in self._workflows.values()
                if workflow.item_id == str(item_id)
                and workflow.status in {"active", "verifying"}
                and workflow.steps
                and workflow.current_step_index == len(workflow.steps) - 1
            ]
            if not candidates:
                return False
            candidates.sort(key=lambda workflow: workflow.updated_at, reverse=True)
            workflow = candidates[0]
            step = workflow.current_step()
            if step is None or step.status in {"completed", "cancelled"}:
                return False
            if _is_verification_step(step) and step.attempts <= 0:
                return False
            step.status = "completed"
            step.evidence = step.evidence or "Final delivery confirmed."
            workflow.status = "ready_to_report"
            workflow.blocker = ""
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)
            ticket_ids = [
                workflow.reply_ticket_id,
                *workflow.reply_ticket_ids,
            ]
        for ticket_id in ticket_ids:
            if ticket_id:
                self.on_delivery(ticket_id)
                break
        else:
            with self._lock:
                workflow.status = "completed"
                workflow.updated_at = _utcnow()
                _persist_workflow(workflow)
        return True

    def can_finalize(self, ticket_id: str) -> tuple[bool, str]:
        workflow = self.get_by_ticket(ticket_id)
        if not workflow:
            return True, ""
        if workflow.status == "blocked" and workflow.awaiting_kind:
            return (
                False,
                "The task is waiting for a recoverable prerequisite and must remain in "
                f"the task queue. Awaiting: {workflow.awaiting_kind}"
                f"{f' ({workflow.awaiting_key})' if workflow.awaiting_key else ''}.",
            )
        if workflow.status in {
            "ready_to_report",
            "blocked",
            "cancelled",
            "completed",
        }:
            return True, ""
        step = workflow.current_step()
        current = step.title if step else "unknown"
        return (
            False,
            "The main task workflow is not finished. "
            f"Objective: {workflow.objective}. Current step: {current}. "
            "A sentence describing a next step, recommendation, or intention is not progress. "
            "Do not answer with 'next I will', 'I suggest', 'shall I', or an incomplete status. "
            "Call one concrete execution tool now. If the previous method failed, add a recovery "
            "step and immediately execute the safe recovery action. Package, mirror, dependency, "
            "or command errors are recoverable work, not user blockers. Mark blocked only when "
            "missing user input, permission, or an external prerequisite genuinely prevents action.",
        )

    def on_delivery(self, ticket_id: str) -> None:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return
            if workflow.status == "blocked" and workflow.awaiting_kind:
                workflow.queue_status = "waiting"
                workflow.updated_at = _utcnow()
                _persist_workflow(workflow)
                return
            now = _utcnow()
            workflow.delivered_at = now
            if workflow.status in {"ready_to_report", "reporting", "active", "verifying", "waiting_job"}:
                workflow.status = "completed"
                for step in workflow.steps:
                    if step.status not in {"completed", "cancelled"}:
                        step.status = "completed"
            elif workflow.status == "blocked":
                workflow.status = "failed"
                for index, step in enumerate(workflow.steps):
                    if step.status in {"completed", "cancelled"}:
                        continue
                    step.status = (
                        "failed"
                        if index == workflow.current_step_index
                        else "cancelled"
                    )
            workflow.updated_at = now
            _persist_workflow(workflow)

    def mark_delivery_failed(self, ticket_id: str, error: str) -> None:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return
            delivery_error = str(error or "delivery failed")[:1000]
            if workflow.status in {"ready_to_report", "reporting"}:
                workflow.status = "ready_to_report"
                workflow.blocker = delivery_error
            else:
                workflow.latest_progress = (
                    f"Intermediate delivery failed: {delivery_error}"
                )
            workflow.updated_at = _utcnow()
            _persist_workflow(workflow)

    def snapshot(self, item_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            workflows = list(self._workflows.values())
        if item_id:
            workflows = [
                workflow for workflow in workflows if workflow.item_id == str(item_id)
            ]
        workflows.sort(key=lambda workflow: workflow.updated_at, reverse=True)
        return [self._snapshot_workflow(workflow) for workflow in workflows]

    def snapshot_for_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        workflow = self.get_by_ticket(ticket_id)
        return self._snapshot_workflow(workflow) if workflow else None

    def _snapshot_workflow(self, workflow: TaskWorkflow) -> dict[str, Any]:
        return workflow_to_payload(workflow)

    def build_prompt_context(
        self,
        *,
        item_id: str,
        reply_ticket_id: str = "",
    ) -> str:
        workflow = self.get_by_ticket(reply_ticket_id) if reply_ticket_id else None
        if workflow is None or workflow.status in WORKFLOW_FINAL_STATUSES:
            return ""

        current = workflow.current_step()
        lines = [
            "Authoritative task workflow (state machine):",
            f"- workflow_id: {workflow.workflow_id}",
            f"- main_objective: {workflow.objective}",
            f"- status: {workflow.status}",
            f"- return_source: {workflow.source_label or workflow.source_type}",
            f"- return_target_count: {len(workflow.reply_ticket_ids)}",
            f"- report_policy: {workflow.report_policy}",
            f"- current_step: {workflow.current_step_index + 1}/{len(workflow.steps)} "
            f"{current.title if current else '(none)'}",
        ]
        if workflow.latest_progress:
            lines.append(f"- latest_progress: {workflow.latest_progress}")
        if workflow.latest_user_instruction:
            lines.append(
                f"- latest_user_instruction: {workflow.latest_user_instruction}"
            )
        if workflow.blocker:
            lines.append(f"- blocker: {workflow.blocker}")
        lines.append("- steps:")
        for index, step in enumerate(workflow.steps, start=1):
            recovery = " recovery" if step.recovery else ""
            evidence = f" evidence={step.evidence[-300:]}" if step.evidence else ""
            error = f" error={step.last_error[-300:]}" if step.last_error else ""
            lines.append(
                f"  {index}. [{step.status}{recovery}] {step.title}{evidence}{error}"
            )
        running_jobs = [job for job in workflow.jobs if job.status == "running"]
        if running_jobs:
            lines.append("- running_jobs:")
            for job in running_jobs[-5:]:
                bound_step = workflow.find_step_by_id(job.step_id)
                step_label = f" (step: {bound_step.title})" if bound_step else ""
                lines.append(f"  - {job.workflow_job_id}: {job.command}{step_label}")
        lines.extend(
            [
                "Non-negotiable workflow rules:",
                "1. The main_objective is immutable. A source change, apt update, retry, "
                "download, inspection, or error recovery is only a substep.",
                "2. After a failed substep, adapt the method and continue the same objective. "
                "Use mcp_local_update_task_workflow(action=insert_recovery_step) when needed.",
                "3. After observed evidence, call mcp_local_update_task_workflow to record "
                "progress or complete the current step. Do not rely on memory to advance it.",
                "4. Do not give a final completion answer while this workflow is active or "
                "waiting_job. Finish verification first, or mark a genuine blocker.",
                "5. Report success/failure back only through the linked reply ticket source.",
                "6. Multi-step, asynchronous, or wait-for-response work continues through this "
                "workflow across turns. Ordinary chat and immediate one-step actions do not "
                "need a workflow.",
                "7. Cancelling an obsolete command or background job does not cancel the main "
                "objective. Use mcp_local_cancel_job for the execution, then continue the workflow. "
                "Use workflow action=cancel only when the user explicitly abandons the whole goal.",
                "8. Do not stop at a diagnosis or proposed next step when a safe tool action is "
                "available. Execute one concrete action in the current turn.",
                "9. When report_policy is final_only, do not send intermediate progress messages. "
                "Continue working and send one concise report only after verified success or final failure.",
                "10. Independent workflows may run background jobs in parallel. Choose the "
                "execution order yourself from the task plan and current evidence; do not create "
                "a task-level waiting/blocking state merely because another task is running.",
                "11. Never leave a task paused because a model turn did not converge. Continue "
                "automatically within the retry limit; after that, report the actual failure to "
                "the immutable source and remove the task queue entry.",
                "12. A repeated request for this same objective reuses this workflow. Read the "
                "current step, latest_progress, evidence, and running_jobs before acting; never "
                "restart an operation merely because the user repeated the request.",
                "13. The final report goes back to the current reply ticket's source directly "
                "as the visible answer; do not send separate duplicate reports manually.",
                "14. Step completion requires fresh evidence from THIS run: a command "
                "output, exit code, or live check result. Long-term memory and chat history "
                "answer who/what, never that something is installed, running, or done now. "
                "Before completing any 检查/验证 step, run the check command and use its "
                "actual output as evidence.",
            ]
        )
        return "\n".join(lines)


task_workflow_manager = TaskWorkflowManager()
