from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.plugins.robot.bridge import embedded


def _idle_bridge_client(reason: str = "no_enabled_robots") -> TestClient:
    app = FastAPI()
    app.include_router(embedded._build_idle_bridge_router(reason))
    return TestClient(app)


def test_idle_bridge_reload_without_enabled_robot_does_not_503(
    monkeypatch,
) -> None:
    monkeypatch.setattr(embedded, "_read_owner_info", lambda: None)
    monkeypatch.setattr(
        embedded,
        "_current_enabled_robot_config_signature",
        lambda: ([], {}, {}, {}),
    )

    with _idle_bridge_client() as client:
        response = client.post(
            "/robot-bridge/internal/reload",
            headers={
                "X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET
                or settings.SECRET_KEY,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "detail": "Bridge is idle (no_enabled_robots); no enabled robots are configured",
    }


def test_idle_bridge_reload_with_enabled_robot_schedules_restart(
    monkeypatch,
) -> None:
    robot = SimpleNamespace(
        id=uuid4(),
        platform="onebot_v11",
        protocol="onebot_v11",
        config={
            "credentials": {
                "self_id": "1024",
                "ws_url": "ws://napcat.test:3001",
            },
            "options": {},
        },
    )
    scheduled_reasons: list[str] = []
    monkeypatch.setattr(embedded, "_read_owner_info", lambda: None)
    monkeypatch.setattr(
        embedded,
        "_current_enabled_robot_config_signature",
        lambda: (
            [robot],
            {},
            {str(robot.id): f"onebot_v11:{robot.config['credentials']['self_id']}"},
            {},
        ),
    )
    monkeypatch.setattr(
        embedded,
        "_schedule_process_restart",
        lambda reason: scheduled_reasons.append(reason) is None or True,
    )

    with _idle_bridge_client() as client:
        response = client.post(
            "/robot-bridge/internal/reload",
            headers={
                "X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET
                or settings.SECRET_KEY,
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "restart was scheduled" in response.json()["detail"]
    assert scheduled_reasons == [
        "embedded robot bridge was idle (no_enabled_robots); reload requested with enabled robots"
    ]


def test_idle_bridge_reload_with_missing_owner_does_not_restart_proxy_worker(
    monkeypatch,
) -> None:
    robot = SimpleNamespace(
        id=uuid4(),
        platform="onebot_v11",
        protocol="onebot_v11",
        config={
            "credentials": {
                "self_id": "2048",
                "ws_url": "ws://napcat.test:3001",
            },
            "options": {},
        },
    )
    scheduled_reasons: list[str] = []
    monkeypatch.setattr(embedded, "_read_owner_info", lambda: None)
    monkeypatch.setattr(
        embedded,
        "_current_enabled_robot_config_signature",
        lambda: (
            [robot],
            {},
            {str(robot.id): f"onebot_v11:{robot.config['credentials']['self_id']}"},
            {},
        ),
    )
    monkeypatch.setattr(
        embedded,
        "_schedule_process_restart",
        lambda reason: scheduled_reasons.append(reason) is None or True,
    )

    with _idle_bridge_client("robot_bridge_lock_owned_by_another_process") as client:
        response = client.post(
            "/robot-bridge/internal/reload",
            headers={
                "X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET
                or settings.SECRET_KEY,
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "owner is not available" in response.json()["detail"]
    assert scheduled_reasons == []
