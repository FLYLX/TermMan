from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WORKFLOW_ACTIVE_STATUSES = {
    "active",
    "waiting_job",
    "verifying",
    "blocked",
    "ready_to_report",
    "reporting",
}
WORKFLOW_FINAL_STATUSES = {"completed", "cancelled"}
STEP_ACTIVE_STATUSES = {"running", "waiting", "failed"}
MAX_WORKFLOWS_PER_ITEM = 8
COMPLETED_RETENTION = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return _utcnow()
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    status: str = "active"
    current_step_index: int = 0
    latest_progress: str = ""
    blocker: str = ""
    last_tool_name: str = ""
    last_command: str = ""
    jobs: list[WorkflowJob] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    delivered_at: datetime | None = None

    def current_step(self) -> WorkflowStep | None:
        if not self.steps:
            return None
        index = max(0, min(self.current_step_index, len(self.steps) - 1))
        return self.steps[index]


class TaskWorkflowManager:
    def __init__(
        self,
        *,
        state_path: Path | None = None,
        persist: bool | None = None,
    ) -> None:
        backend_dir = Path(__file__).resolve().parents[3]
        configured_path = os.getenv("TASK_WORKFLOW_STATE_PATH", "").strip()
        self._state_path = state_path or (
            Path(configured_path)
            if configured_path
            else backend_dir / ".runtime" / "task_workflows.json"
        )
        if persist is None:
            persist = os.getenv(
                "TASK_WORKFLOW_PERSIST", "true"
            ).strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        self._persist = bool(persist)
        self._workflows: dict[str, TaskWorkflow] = {}
        self._ticket_to_workflow: dict[str, str] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._persist or not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        raw_workflows = payload.get("workflows") if isinstance(payload, dict) else []
        if not isinstance(raw_workflows, list):
            return
        with self._lock:
            for raw in raw_workflows:
                workflow = self._workflow_from_dict(raw)
                if workflow is None:
                    continue
                self._workflows[workflow.workflow_id] = workflow
                if workflow.reply_ticket_id:
                    self._ticket_to_workflow[workflow.reply_ticket_id] = (
                        workflow.workflow_id
                    )
            self._prune_locked(_utcnow())

    def _workflow_from_dict(self, raw: Any) -> TaskWorkflow | None:
        if not isinstance(raw, dict):
            return None
        try:
            steps = [
                WorkflowStep(**step)
                for step in raw.get("steps", [])
                if isinstance(step, dict)
            ]
            jobs = [
                WorkflowJob(
                    **{
                        **job,
                        "started_at": _parse_datetime(job.get("started_at")),
                        "completed_at": _parse_datetime(job.get("completed_at"))
                        if job.get("completed_at")
                        else None,
                    }
                )
                for job in raw.get("jobs", [])
                if isinstance(job, dict)
            ]
            return TaskWorkflow(
                workflow_id=str(raw["workflow_id"]),
                item_id=str(raw["item_id"]),
                handler_id=str(raw.get("handler_id") or ""),
                reply_ticket_id=str(raw.get("reply_ticket_id") or ""),
                objective=str(raw.get("objective") or ""),
                source_type=str(raw.get("source_type") or "web"),
                source_label=str(raw.get("source_label") or ""),
                steps=steps,
                status=str(raw.get("status") or "active"),
                current_step_index=int(raw.get("current_step_index") or 0),
                latest_progress=str(raw.get("latest_progress") or ""),
                blocker=str(raw.get("blocker") or ""),
                last_tool_name=str(raw.get("last_tool_name") or ""),
                last_command=str(raw.get("last_command") or ""),
                jobs=jobs,
                created_at=_parse_datetime(raw.get("created_at")),
                updated_at=_parse_datetime(raw.get("updated_at")),
                delivered_at=_parse_datetime(raw.get("delivered_at"))
                if raw.get("delivered_at")
                else None,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _workflow_to_dict(self, workflow: TaskWorkflow) -> dict[str, Any]:
        payload = asdict(workflow)
        payload["created_at"] = _iso(workflow.created_at)
        payload["updated_at"] = _iso(workflow.updated_at)
        payload["delivered_at"] = _iso(workflow.delivered_at)
        for index, job in enumerate(workflow.jobs):
            payload["jobs"][index]["started_at"] = _iso(job.started_at)
            payload["jobs"][index]["completed_at"] = _iso(job.completed_at)
        return payload

    def _save_locked(self) -> None:
        if not self._persist:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _iso(_utcnow()),
            "workflows": [
                self._workflow_to_dict(workflow)
                for workflow in self._workflows.values()
            ],
        }
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._state_path.parent,
            prefix=f".{self._state_path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temp_path = Path(handle.name)
        try:
            with handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._state_path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

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
            if workflow and workflow.reply_ticket_id:
                self._ticket_to_workflow.pop(workflow.reply_ticket_id, None)

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
                if workflow.reply_ticket_id:
                    self._ticket_to_workflow.pop(workflow.reply_ticket_id, None)

    def reset(self, *, clear_persisted: bool = False) -> None:
        with self._lock:
            self._workflows.clear()
            self._ticket_to_workflow.clear()
            if clear_persisted and self._persist:
                self._state_path.unlink(missing_ok=True)

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
            self._save_locked()
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
            if workflow.reply_ticket_id:
                self._ticket_to_workflow.pop(workflow.reply_ticket_id, None)
            workflow.reply_ticket_id = str(ticket_id or "")
            workflow.updated_at = _utcnow()
            if ticket_id:
                self._ticket_to_workflow[str(ticket_id)] = workflow.workflow_id
            self._save_locked()
            return True

    def find_resumable(
        self,
        *,
        item_id: str,
        source_type: str,
        source_label: str,
    ) -> TaskWorkflow | None:
        with self._lock:
            candidates = [
                workflow
                for workflow in self._workflows.values()
                if workflow.item_id == str(item_id)
                and workflow.source_type == str(source_type)
                and workflow.source_label == str(source_label)
                and workflow.status in {"blocked", "active", "waiting_job", "verifying"}
            ]
        candidates.sort(key=lambda workflow: workflow.updated_at, reverse=True)
        return candidates[0] if candidates else None

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
            self._save_locked()

    def mark_job_started(self, ticket_id: str, *, command: str) -> str:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return ""
            job = WorkflowJob(
                workflow_job_id=uuid.uuid4().hex[:12],
                command=str(command or "").strip()[:2000],
            )
            workflow.jobs.append(job)
            workflow.jobs = workflow.jobs[-12:]
            workflow.status = "waiting_job"
            workflow.latest_progress = f"Background job running: {job.command}"
            workflow.updated_at = _utcnow()
            self._save_locked()
            return job.workflow_job_id

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
            self._save_locked()

    def record_job_result(
        self,
        ticket_id: str,
        *,
        command: str,
        success: bool,
        result_summary: str,
        daemon_job_id: str = "",
        exit_code: int | None = None,
    ) -> None:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
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
                job = WorkflowJob(
                    workflow_job_id=uuid.uuid4().hex[:12],
                    command=normalized_command,
                )
                workflow.jobs.append(job)
            job.status = "succeeded" if success else "failed"
            job.success = bool(success)
            job.daemon_job_id = str(daemon_job_id or "")
            job.exit_code = exit_code
            job.result_summary = str(result_summary or "").strip()[-2000:]
            job.completed_at = _utcnow()
            step = workflow.current_step()
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
            workflow.updated_at = _utcnow()
            self._save_locked()

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
            self._save_locked()
            return True, workflow.status

    def can_finalize(self, ticket_id: str) -> tuple[bool, str]:
        workflow = self.get_by_ticket(ticket_id)
        if not workflow:
            return True, ""
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
            "Continue the task, or call mcp_local_update_task_workflow to record "
            "progress, complete the current step, add a recovery step, or mark a real blocker.",
        )

    def on_delivery(self, ticket_id: str) -> None:
        with self._lock:
            workflow = self.get_by_ticket(ticket_id)
            if not workflow:
                return
            now = _utcnow()
            workflow.delivered_at = now
            if workflow.status in {"ready_to_report", "reporting"}:
                workflow.status = "completed"
                for step in workflow.steps:
                    if step.status not in {"completed", "cancelled"}:
                        step.status = "completed"
            workflow.updated_at = now
            self._save_locked()

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
            self._save_locked()

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
        current = workflow.current_step()
        return {
            "workflow_id": workflow.workflow_id,
            "item_id": workflow.item_id,
            "handler_id": workflow.handler_id,
            "reply_ticket_id": workflow.reply_ticket_id,
            "objective": workflow.objective,
            "source_type": workflow.source_type,
            "source_label": workflow.source_label,
            "status": workflow.status,
            "current_step_index": workflow.current_step_index,
            "current_step": current.title if current else "",
            "latest_progress": workflow.latest_progress,
            "blocker": workflow.blocker,
            "last_tool_name": workflow.last_tool_name,
            "last_command": workflow.last_command,
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

    def build_prompt_context(
        self,
        *,
        item_id: str,
        reply_ticket_id: str = "",
    ) -> str:
        workflow = self.get_by_ticket(reply_ticket_id) if reply_ticket_id else None
        if workflow is None:
            with self._lock:
                active = [
                    candidate
                    for candidate in self._workflows.values()
                    if candidate.item_id == str(item_id)
                    and candidate.status in WORKFLOW_ACTIVE_STATUSES
                ]
            active.sort(key=lambda candidate: candidate.updated_at, reverse=True)
            workflow = active[0] if len(active) == 1 else None
        if workflow is None:
            return ""

        current = workflow.current_step()
        lines = [
            "Authoritative task workflow (state machine):",
            f"- workflow_id: {workflow.workflow_id}",
            f"- main_objective: {workflow.objective}",
            f"- status: {workflow.status}",
            f"- return_source: {workflow.source_label or workflow.source_type}",
            f"- current_step: {workflow.current_step_index + 1}/{len(workflow.steps)} "
            f"{current.title if current else '(none)'}",
        ]
        if workflow.latest_progress:
            lines.append(f"- latest_progress: {workflow.latest_progress}")
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
                lines.append(f"  - {job.workflow_job_id}: {job.command}")
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
            ]
        )
        return "\n".join(lines)


task_workflow_manager = TaskWorkflowManager()
