from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.utils.item import create_random_item


def test_get_all_memories_requires_permissions(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    item = create_random_item(db)

    response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/memories",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403


def test_get_all_memories_sorts_active_status_first(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import memory as memory_route

    item = create_random_item(db)

    monkeypatch.setattr(
        memory_route.vector_store,
        "get_all_memories",
        lambda *args, **kwargs: [
            {
                "id": "fact-1",
                "content": "cron_job.py 位于 /app/src/cron_job.py",
                "metadata": {
                    "memory_type": "fact",
                    "updated_at": "2026-04-02T10:00:00",
                },
            },
            {
                "id": "task-closed",
                "content": "当前任务：修复 daemon 状态同步（已完成）",
                "metadata": {
                    "memory_type": "task",
                    "status": "completed",
                    "updated_at": "2026-04-02T11:00:00",
                },
            },
            {
                "id": "error-active",
                "content": "已知错误：cron_job.py 找不到",
                "metadata": {
                    "memory_type": "error",
                    "status": "active",
                    "updated_at": "2026-04-02T09:00:00",
                },
            },
        ],
    )

    response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/memories",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert [memory["id"] for memory in payload["memories"]] == [
        "error-active",
        "fact-1",
    ]


def test_get_all_memories_supports_status_filter_and_pagination(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import memory as memory_route

    item = create_random_item(db)

    monkeypatch.setattr(
        memory_route.vector_store,
        "get_all_memories",
        lambda *args, **kwargs: [
            {
                "id": "error-old",
                "content": "已知错误：旧错误",
                "metadata": {
                    "memory_type": "error",
                    "status": "active",
                    "updated_at": "2026-04-02T09:00:00",
                },
            },
            {
                "id": "error-new",
                "content": "已知错误：新错误",
                "metadata": {
                    "memory_type": "error",
                    "status": "active",
                    "updated_at": "2026-04-02T11:00:00",
                },
            },
            {
                "id": "error-resolved",
                "content": "已知错误：已解决错误（已解决）",
                "metadata": {
                    "memory_type": "error",
                    "status": "resolved",
                    "updated_at": "2026-04-02T12:00:00",
                },
            },
        ],
    )

    response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/memories",
        headers=superuser_token_headers,
        params={"memory_status": "active", "offset": 0, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["offset"] == 0
    assert payload["limit"] == 1
    assert payload["has_more"] is True
    assert [memory["id"] for memory in payload["memories"]] == ["error-new"]


def test_get_memory_stats_includes_status_counts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import memory as memory_route

    item = create_random_item(db)
    fake_memories = [
        {
            "id": "task-1",
            "content": "当前任务：修复 daemon 状态同步",
            "metadata": {"memory_type": "task", "status": "active"},
        },
        {
            "id": "task-2",
            "content": "当前任务：补中断按钮（已完成）",
            "metadata": {"memory_type": "task", "status": "completed"},
        },
        {
            "id": "error-1",
            "content": "已知错误：cron_job.py 找不到",
            "metadata": {"memory_type": "error", "status": "resolved"},
        },
    ]

    monkeypatch.setattr(memory_route.vector_store, "get_all_memories", lambda *args, **kwargs: fake_memories)
    response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/memories/stats",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status_counts"] == {
        "error": {"active": 0, "resolved": 1},
    }
    assert payload["total"] == 1
    assert "task" not in payload["by_type"]
    assert payload["by_type"]["error"] == 1


def test_update_memory_status_rejects_removed_task_memory(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import memory as memory_route

    item = create_random_item(db)
    monkeypatch.setattr(
        memory_route.vector_store,
        "get_memory",
        lambda memory_id: {
            "id": memory_id,
            "content": "当前任务：修复 daemon 状态同步",
            "metadata": {
                "item_id": str(item.id),
                "memory_type": "task",
                "status": "active",
                "created_at": "2026-04-02T09:00:00",
            },
        },
    )

    response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/memories/task-1/status",
        headers=superuser_token_headers,
        json={"status": "resolved"},
    )

    assert response.status_code == 400


def test_add_memory_rejects_removed_task_type(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import memory as memory_route

    item = create_random_item(db)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        memory_route.vector_store,
        "add_memory",
        lambda **kwargs: captured.update(kwargs) or "task-memory-1",
    )

    response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/memories",
        headers=superuser_token_headers,
        json={"content": "安装 Java", "memory_type": "task"},
    )

    assert response.status_code == 422
    assert captured == {}


def test_update_memory_status_rejects_invalid_type_transition(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import memory as memory_route

    item = create_random_item(db)

    monkeypatch.setattr(
        memory_route.vector_store,
        "get_memory",
        lambda memory_id: {
            "id": memory_id,
            "content": "cron_job.py 位于 /app/src/cron_job.py",
            "metadata": {
                "item_id": str(item.id),
                "memory_type": "fact",
                "created_at": "2026-04-02T09:00:00",
            },
        },
    )

    response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/memories/fact-1/status",
        headers=superuser_token_headers,
        json={"status": "resolved"},
    )

    assert response.status_code == 400


def test_update_memory_status_requires_memory_belongs_to_item(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import memory as memory_route

    item = create_random_item(db)

    monkeypatch.setattr(
        memory_route.vector_store,
        "get_memory",
        lambda memory_id: {
            "id": memory_id,
            "content": "已知错误：daemon 状态同步失败",
            "metadata": {
                "item_id": "another-item",
                "memory_type": "error",
                "status": "active",
                "created_at": "2026-04-02T09:00:00",
            },
        },
    )

    response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/memories/error-2/status",
        headers=superuser_token_headers,
        json={"status": "resolved"},
    )

    assert response.status_code == 404


def test_installed_software_api_allows_manual_edit(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
    tmp_path,
) -> None:
    import app.services.agent.installed_software as installed_software

    monkeypatch.setattr(installed_software, "_INSTALLED_SOFTWARE_DIR", tmp_path)
    item = create_random_item(db)

    create_response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/installed-software",
        headers=superuser_token_headers,
        json={
            "name": "openjdk-21-jdk-headless",
            "manager": "apt",
            "version": "21",
            "command": "apt-get install -y openjdk-21-jdk-headless",
            "notes": "verified with java -version",
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["item"]["name"] == "openjdk-21-jdk-headless"

    list_response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/installed-software",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["version"] == "21"

    update_response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/installed-software",
        headers=superuser_token_headers,
        json={
            "name": "openjdk-21-jdk-headless",
            "manager": "apt",
            "version": "21.0.1",
        },
    )
    assert update_response.status_code == 200

    delete_response = client.request(
        "DELETE",
        f"{settings.API_V1_STR}/memory/{item.id}/installed-software",
        headers=superuser_token_headers,
        json={"name": "openjdk-21-jdk-headless", "manager": "apt"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["count"] == 1

    empty_response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/installed-software",
        headers=superuser_token_headers,
    )
    assert empty_response.status_code == 200
    assert empty_response.json()["items"] == []


def test_scheduled_tasks_api_allows_manual_crud(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
    tmp_path,
) -> None:
    import app.services.agent.scheduled_tasks as scheduled_tasks

    monkeypatch.setattr(scheduled_tasks, "_SCHEDULED_TASKS_DIR", tmp_path)
    item = create_random_item(db)

    create_response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/scheduled-tasks",
        headers=superuser_token_headers,
        json={
            "name": "daily terminal check",
            "instruction": "Check the terminal and report any failures.",
            "schedule_type": "daily",
            "time_of_day": "09:00",
            "timezone": "Asia/Shanghai",
            "enabled": True,
        },
    )
    assert create_response.status_code == 200
    task_id = create_response.json()["item"]["id"]

    list_response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/scheduled-tasks",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert list_response.json()["items"][0]["name"] == "daily terminal check"

    update_response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/scheduled-tasks",
        headers=superuser_token_headers,
        json={
            "task_id": task_id,
            "name": "daily terminal check",
            "instruction": "Check the terminal and report any failures.",
            "schedule_type": "daily",
            "time_of_day": "10:00",
            "timezone": "Asia/Shanghai",
            "enabled": False,
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["item"]["enabled"] is False

    delete_response = client.delete(
        f"{settings.API_V1_STR}/memory/{item.id}/scheduled-tasks/{task_id}",
        headers=superuser_token_headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["count"] == 1
