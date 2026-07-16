from sqlmodel import Session

from app.services.terminal_runtime_state import get_terminal_runtime_state
from tests.utils.item import create_random_item


def _patch_connection(monkeypatch, connection) -> None:
    import app.services as services_module

    monkeypatch.setattr(
        services_module.connection_manager,
        "get_or_create_connection",
        lambda _config: connection,
    )


def test_live_terminal_state_requires_backend_room(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)

    class FakeConnection:
        def is_connected(self):
            return True

        def terminal_status_http(self, item_uuid, timeout=30.0):
            assert item_uuid == str(item.id)
            assert timeout == 5.0
            return {
                "success": True,
                "data": {
                    "status": "running",
                    # A stale RoomManager entry must not override the live
                    # disconnected Room socket flag.
                    "room_info": {"permanent_count": 1, "temporary_count": 1},
                    "backend_room_connected": False,
                },
            }

    _patch_connection(monkeypatch, FakeConnection())

    state = get_terminal_runtime_state(str(item.id))

    assert state.terminal_process_active is True
    assert state.backend_room_connected is False
    assert state.permanent_subscriber_count == 1
    assert state.active is False
    assert state.reason == "backend_room_not_connected"


def test_live_terminal_state_is_active_after_backend_joins_room(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)

    class FakeConnection:
        def is_connected(self):
            return True

        def terminal_status_http(self, item_uuid, timeout=30.0):
            assert item_uuid == str(item.id)
            assert timeout == 5.0
            return {
                "success": True,
                "data": {
                    "status": "running",
                    "room_info": {"permanent_count": 1, "temporary_count": 0},
                    "backend_room_connected": True,
                },
            }

    _patch_connection(monkeypatch, FakeConnection())

    state = get_terminal_runtime_state(str(item.id))

    assert state.active is True
    assert state.daemon_connected is True
    assert state.backend_room_connected is True
    assert state.permanent_subscriber_count == 1
    assert state.reason == "active"


def test_live_terminal_state_reports_daemon_disconnect(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)

    class FakeConnection:
        def is_connected(self):
            return False

        def terminal_status_http(self, *_args, **_kwargs):
            raise AssertionError("disconnected daemon must not receive status requests")

    _patch_connection(monkeypatch, FakeConnection())

    state = get_terminal_runtime_state(str(item.id))

    assert state.active is False
    assert state.daemon_connected is False
    assert state.reason == "daemon_not_connected"
