from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.services.agent.task_workflow import task_workflow_manager

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
