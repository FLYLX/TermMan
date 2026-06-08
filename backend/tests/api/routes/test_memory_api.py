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
        "task-closed",
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
                "id": "task-old",
                "content": "当前任务：旧任务",
                "metadata": {
                    "memory_type": "task",
                    "status": "active",
                    "updated_at": "2026-04-02T09:00:00",
                },
            },
            {
                "id": "task-new",
                "content": "当前任务：新任务",
                "metadata": {
                    "memory_type": "task",
                    "status": "active",
                    "updated_at": "2026-04-02T11:00:00",
                },
            },
            {
                "id": "task-done",
                "content": "当前任务：已完成任务（已完成）",
                "metadata": {
                    "memory_type": "task",
                    "status": "completed",
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
    assert [memory["id"] for memory in payload["memories"]] == ["task-new"]


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
    monkeypatch.setattr(
        memory_route.vector_store,
        "get_memory_stats",
        lambda *args, **kwargs: {
            "total": 3,
            "by_type": {"task": 2, "error": 1},
            "expired_count": 0,
        },
    )

    response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/memories/stats",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status_counts"] == {
        "task": {"active": 1, "completed": 1},
        "error": {"active": 0, "resolved": 1},
    }


def test_update_memory_status_updates_task_content_and_status(
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

    def fake_update_memory(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(memory_route.vector_store, "update_memory", fake_update_memory)

    response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/memories/task-1/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )

    assert response.status_code == 200
    assert captured["memory_id"] == "task-1"
    assert captured["content"] == "当前任务：修复 daemon 状态同步（已完成）"
    assert captured["metadata"]["status"] == "completed"


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
        json={"status": "completed"},
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
            "content": "当前任务：修复 daemon 状态同步",
            "metadata": {
                "item_id": "another-item",
                "memory_type": "task",
                "status": "active",
                "created_at": "2026-04-02T09:00:00",
            },
        },
    )

    response = client.post(
        f"{settings.API_V1_STR}/memory/{item.id}/memories/task-2/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )

    assert response.status_code == 404
