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
    """List task workflows for one item, newest activity first.

    This is the task queue the agent plans, executes, and reports through:
    objective, planned steps with per-step status, current progress, and the
    immutable report destination (QQ conversation / web / terminal).
    """
    _ = current_user
    workflows = task_workflow_manager.snapshot(item_id)[:MAX_WORKFLOWS_RETURNED]
    return {"workflows": workflows, "count": len(workflows)}


@router.post("/{workflow_id}/cancel")
def cancel_task_workflow(workflow_id: str, current_user: CurrentUser) -> dict:
    """Cancel one non-final task workflow (user-initiated)."""
    _ = current_user
    workflow = task_workflow_manager.get(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="task workflow not found")

    if workflow.status not in WORKFLOW_FINAL_STATUSES:
        ticket_id = workflow.reply_ticket_id or (
            workflow.reply_ticket_ids[-1] if workflow.reply_ticket_ids else ""
        )
        if ticket_id:
            task_workflow_manager.update(
                ticket_id,
                action="cancel",
                note="User cancelled the task from the task queue panel.",
            )
        else:
            workflow.status = "cancelled"
    snapshot = task_workflow_manager.snapshot_for_ticket(
        workflow.reply_ticket_id or workflow_id
    )
    return {"workflow": snapshot}

