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


def test_list_hides_finished_workflows_after_retention(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    from datetime import datetime, timedelta, timezone

    task_workflow_manager.reset()
    try:
        fresh_final = task_workflow_manager.create(
            item_id="item-1",
            handler_id="handler-1",
            reply_ticket_id="ticket-fresh",
            objective="刚取消的任务",
            source_type="web",
            source_label="web",
            step_titles=["一步"],
        )
        task_workflow_manager.update("ticket-fresh", action="cancel", note="取消")
        old_final = task_workflow_manager.create(
            item_id="item-1",
            handler_id="handler-1",
            reply_ticket_id="ticket-old",
            objective="早就完成的任务",
            source_type="web",
            source_label="web",
            step_titles=["一步"],
        )
        task_workflow_manager.update("ticket-old", action="cancel", note="取消")
        old_final.updated_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        active = task_workflow_manager.create(
            item_id="item-1",
            handler_id="handler-1",
            reply_ticket_id="ticket-active",
            objective="进行中的任务",
            source_type="web",
            source_label="web",
            step_titles=["一步", "两步"],
        )
        active.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)

        response = client.get(
            f"{settings.API_V1_STR}/task-workflows/item-1",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200, response.text
        objectives = {
            entry["objective"] for entry in response.json()["workflows"]
        }
        assert "刚取消的任务" not in objectives, "finished tasks drop off immediately"
        assert "早就完成的任务" not in objectives, "old finals drop off the panel"
        assert "进行中的任务" in objectives, "active tasks are always shown"
        assert response.json()["count"] == 1
        assert fresh_final.status == "cancelled"
    finally:
        task_workflow_manager.reset()
