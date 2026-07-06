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


def test_stale_onebot_message_event_payload_ignores_startup_history(monkeypatch) -> None:
    monkeypatch.setattr(embedded, "_bridge_started_at_epoch", 1000.0)
    monkeypatch.setattr(embedded, "_stale_onebot_message_grace_seconds", 1.0)
    event = SimpleNamespace(
        model_dump=lambda: {
            "post_type": "message",
            "time": 998,
            "message_type": "group",
            "raw_message": "old cached message",
        }
    )

    stale_payload = embedded._stale_onebot_message_event_payload(
        event,
        embedded._serialize_event_payload(event),
    )

    assert stale_payload is not None
    assert stale_payload["event_time"] == 998.0


def test_stale_onebot_message_event_payload_allows_realtime_message(monkeypatch) -> None:
    monkeypatch.setattr(embedded, "_bridge_started_at_epoch", 1000.0)
    monkeypatch.setattr(embedded, "_stale_onebot_message_grace_seconds", 1.0)
    event = SimpleNamespace(
        model_dump=lambda: {
            "post_type": "message",
            "time": 1000,
            "message_type": "group",
            "raw_message": "live message",
        }
    )

    assert (
        embedded._stale_onebot_message_event_payload(
            event,
            embedded._serialize_event_payload(event),
        )
        is None
    )


def test_stale_onebot_message_event_payload_ignores_non_message_events(monkeypatch) -> None:
    monkeypatch.setattr(embedded, "_bridge_started_at_epoch", 1000.0)
    monkeypatch.setattr(embedded, "_stale_onebot_message_grace_seconds", 1.0)
    event = SimpleNamespace(
        model_dump=lambda: {
            "post_type": "meta_event",
            "meta_event_type": "heartbeat",
            "time": 1,
        }
    )

    assert (
        embedded._stale_onebot_message_event_payload(
            event,
            embedded._serialize_event_payload(event),
        )
        is None
    )