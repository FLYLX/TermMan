from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.agent.task_workflow import task_workflow_manager


def test_list_task_workflows_returns_planned_steps(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    task_workflow_manager.reset()
    try:
        workflow = task_workflow_manager.create(
            item_id="item-1",
            handler_id="handler-1",
            reply_ticket_id="ticket-1",
            objective="安装 Java",
            source_type="qq",
            source_label="QQ group:g1",
            step_titles=["apt update", "换源", "安装 temurin"],
        )
        task_workflow_manager.update(
            "ticket-1",
            action="record_progress",
            note="apt update 已跑完",
        )

        response = client.get(
            f"{settings.API_V1_STR}/task-workflows/item-1",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["count"] == 1
        entry = payload["workflows"][0]
        assert entry["workflow_id"] == workflow.workflow_id
        assert entry["objective"] == "安装 Java"
        assert entry["source_label"] == "QQ group:g1"
        assert entry["status"] == "active"
        assert entry["latest_progress"] == "apt update 已跑完"
        assert [step["title"] for step in entry["steps"]] == [
            "apt update",
            "换源",
            "安装 temurin",
        ]
    finally:
        task_workflow_manager.reset()


def test_list_task_workflows_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    task_workflow_manager.reset()
    response = client.get(
        f"{settings.API_V1_STR}/task-workflows/item-nothing",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"workflows": [], "count": 0}


def test_cancel_task_workflow(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    task_workflow_manager.reset()
    try:
        workflow = task_workflow_manager.create(
            item_id="item-1",
            handler_id="handler-1",
            reply_ticket_id="ticket-1",
            objective="安装 Java",
            source_type="web",
            source_label="web",
            step_titles=["apt update", "安装 temurin"],
        )

        response = client.post(
            f"{settings.API_V1_STR}/task-workflows/{workflow.workflow_id}/cancel",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["workflow"]["status"] == "cancelled"
        assert task_workflow_manager.get(workflow.workflow_id).status == "cancelled"

        missing = client.post(
            f"{settings.API_V1_STR}/task-workflows/no-such-workflow/cancel",
            headers=superuser_token_headers,
        )
        assert missing.status_code == 404
    finally:
        task_workflow_manager.reset()
