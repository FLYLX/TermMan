from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser
from app.services.agent.task_workflow import (
    WORKFLOW_FINAL_STATUSES,
    task_workflow_manager,
)

router = APIRouter(prefix="/task-workflows", tags=["task-workflows"])

MAX_WORKFLOWS_RETURNED = 20


@router.get("/{item_id}")
def list_task_workflows(item_id: str, current_user: CurrentUser) -> dict:
    """List live (non-final) task workflows for one item.

    This is the task queue the agent plans, executes, and reports through:
    objective, planned steps with per-step status, current progress, and the
    immutable report destination (QQ conversation / web / terminal). Finished
    tasks (completed/failed/cancelled) are reported to their destination and
    immediately dropped from the panel.
    """
    _ = current_user
    visible = [
        entry
        for entry in task_workflow_manager.snapshot(item_id)
        if str(entry.get("status") or "") not in WORKFLOW_FINAL_STATUSES
    ]
    visible = visible[:MAX_WORKFLOWS_RETURNED]
    return {"workflows": visible, "count": len(visible)}


@router.post("/{workflow_id}/cancel")
def cancel_task_workflow(workflow_id: str, current_user: CurrentUser) -> dict:
    """Cancel one non-final task workflow (user-initiated)."""
    _ = current_user
    workflow = task_workflow_manager.get(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="task workflow not found")

    if workflow.status not in WORKFLOW_FINAL_STATUSES:
        task_workflow_manager._cancel_workflow(
            workflow, reason="User cancelled the task from the task queue panel."
        )
        running_commands = {
            str(job.command or "").strip()
            for job in workflow.jobs
            if job.status == "running" and str(job.command or "").strip()
        }
        try:
            from app.services.agent.mcp.local_server import (
                cancel_background_jobs_for_item,
            )

            cancel_background_jobs_for_item(
                workflow.item_id,
                commands=running_commands or None,
            )
        except Exception:
            pass
    snapshot = task_workflow_manager.snapshot_for_ticket(
        workflow.reply_ticket_id or workflow_id
    )
    return {"workflow": snapshot}

