from sqlmodel import Session

from app.services.connection_pool.connection_models import DaemonConfig
from app.services.connection_pool.daemon_connection import DaemonConnection
from app.services.socket_pool.input_center import input_center
from app.services.socket_pool.service_facade import SocketPoolFacade
from app.services.socket_pool.socket_manager import SocketManager
from app.services.socket_pool.subscriber_sdk import ItemSubscriberSDK
from app.services.socket_pool.subscription_center import (
    SubscriptionEvent,
    SubscriptionEventType,
    subscription_center,
)
from app.services.terminal_service import TerminalService
from tests.utils.item import create_random_item


def test_log_subscriber_persists_stdout_and_stderr() -> None:
    sdk = ItemSubscriberSDK()
    writes: list[tuple[str, str, str]] = []

    class FakeLogManager:
        def write_to_log(self, owner_uuid: str, item_uuid: str, content: str) -> None:
            writes.append((owner_uuid, item_uuid, content))

    sub_id = sdk.subscribe_log(
        item_uuid="item-1",
        owner_uuid="user-1",
        log_manager=FakeLogManager(),
    )

    try:
        subscription_center.publish(
            SubscriptionEvent(
                event_type=SubscriptionEventType.STREAM,
                item_uuid="item-1",
                data={"stdout": "out\n", "stderr": "err\n"},
            )
        )
    finally:
        sdk.unsubscribe(sub_id)

    assert writes == [("user-1", "item-1", "out\nerr\n")]


def test_clear_sockets_by_item_disconnects_and_unregisters() -> None:
    manager = SocketManager()
    socket = type(
        "FakeSocket",
        (),
        {
            "item_uuid": "item-1",
            "_input_handler_id": "handler-1",
            "disconnect_called": False,
        },
    )()

    def disconnect():
        socket.disconnect_called = True

    socket.disconnect = disconnect

    original_sockets = manager.sockets.copy()
    manager.sockets = {("backend", "item-1", "backend"): socket}

    unregistered: list[str] = []
    original_unregister = input_center.unregister
    input_center.unregister = lambda handler_id: unregistered.append(handler_id) or True

    try:
        manager.clear_sockets_by_item("item-1")
    finally:
        input_center.unregister = original_unregister
        manager.sockets = original_sockets

    assert socket.disconnect_called is True
    assert unregistered == ["handler-1"]
    assert manager.sockets == {}


def test_daemon_connection_full_sync_uses_rooms_payload(monkeypatch) -> None:
    connection = DaemonConnection(
        DaemonConfig(ip="127.0.0.1", port=9000, api_key="daemon-key")
    )
    callback_payloads: list[dict] = []
    connection.on("connection_update", callback_payloads.append)

    monkeypatch.setattr(
        connection,
        "_emit_and_wait_sync",
        lambda event, data, timeout=10.0: {
            "success": True,
            "connections": {"item-1": {"sid-1": {"user_uuid": "u1", "ip": "127.0.0.1"}}},
        },
    )

    class ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            if self._target:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(
        "app.services.connection_pool.daemon_connection.threading.Thread",
        ImmediateThread,
    )

    connection._sync_all_connections()

    assert callback_payloads == [
        {
            "type": "full_sync",
            "rooms": {"item-1": {"sid-1": {"user_uuid": "u1", "ip": "127.0.0.1"}}},
        }
    ]


def test_socket_pool_facade_cleanup_item_runtime_calls_all_dependencies() -> None:
    calls: list[tuple[str, str]] = []

    class FakeSocketManager:
        def remove_all_tokens_by_item(self, item_uuid: str):
            calls.append(("tokens", item_uuid))

        def clear_sockets_by_item(self, item_uuid: str):
            calls.append(("sockets", item_uuid))

    class FakeSubscriberSDK:
        def unsubscribe(self, subscriber_id: str) -> bool:
            calls.append(("unsubscribe", subscriber_id))
            return True

        def unsubscribe_item(self, item_uuid: str) -> int:
            calls.append(("unsubscribe_item", item_uuid))
            return 1

    facade = SocketPoolFacade(
        socket_manager=FakeSocketManager(),
        subscriber_sdk=FakeSubscriberSDK(),
    )
    facade._log_subscribers = {"item-1": "sub-1"}

    facade.cleanup_item_runtime("item-1")

    assert calls == [
        ("tokens", "item-1"),
        ("sockets", "item-1"),
        ("unsubscribe", "sub-1"),
        ("unsubscribe_item", "item-1"),
    ]


def test_terminal_service_connect_terminal_uses_facade_token_lookup() -> None:
    class FakeSocket:
        def is_connected(self) -> bool:
            return True

    class FakeSocketPoolFacade:
        def get_item_token(self, item_uuid: str):
            return ("daemon-1", "token-1")

        def validate_item_token(self, daemon_id: str, item_uuid: str, token: str) -> bool:
            return True

        def ensure_browser_socket(self, **kwargs):
            return FakeSocket()

    service = TerminalService(connection_manager=None, socket_pool=FakeSocketPoolFacade())
    result = service.connect_terminal(
        item_uuid="item-1",
        token="token-1",
        daemon_url="http://daemon",
        user_uuid="user-1",
    )

    assert result == {"success": True, "item_uuid": "item-1"}


def test_terminal_start_fails_when_backend_room_does_not_connect(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)

    class FakeConnection:
        def is_connected(self) -> bool:
            return True

        def terminal_start_http(self, *args, **kwargs):
            return {
                "success": True,
                "item_uuid": str(item.id),
                "token": "terminal-token",
            }

    class FakeConnectionManager:
        def get_or_create_connection(self, daemon_config):
            return FakeConnection()

    class FakeSocketPool:
        def register_item_token(self, daemon_id, item_uuid, token):
            return None

    service = TerminalService(FakeConnectionManager(), FakeSocketPool())
    monkeypatch.setattr(service, "_create_backend_room_subscriber", lambda *args: False)

    result = service.start_terminal(
        item_uuid=str(item.id),
        user_uuid=str(item.owner_id),
        daemon_config=DaemonConfig("daemon", 9000, "secret"),
    )

    assert result["success"] is False
    assert result["terminal_started"] is True
    assert "Backend 未能进入对应 Socket Room" in result["error"]


def test_restore_running_terminal_rejoins_backend_room(monkeypatch) -> None:
    calls = []

    class FakeConnection:
        def is_connected(self) -> bool:
            return True

        def terminal_status_http(self, item_uuid):
            return {
                "success": True,
                "data": {"status": "running", "token": "restored-token"},
            }

    class FakeConnectionManager:
        def get_or_create_connection(self, daemon_config):
            return FakeConnection()

    service = TerminalService(FakeConnectionManager(), socket_pool=None)
    monkeypatch.setattr(
        service,
        "restore_terminal_session",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    restored = service.restore_running_terminal(
        item_uuid="item-1",
        owner_uuid="user-1",
        daemon_config=DaemonConfig("daemon", 9000, "secret"),
    )

    assert restored is True
    assert calls[0]["token"] == "restored-token"
