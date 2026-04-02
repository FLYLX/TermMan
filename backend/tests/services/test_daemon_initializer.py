from sqlmodel import Session

from app.core.db import engine
from app.models import Item, ItemStatus
from app.services.connection_pool import DaemonConfig, backend_conn_pool
from app.services.daemon_initializer import sync_daemon_connection_state
from tests.utils.item import create_random_item


def test_sync_daemon_connection_state_restores_running_items_from_daemon_snapshot(
    db: Session,
    monkeypatch,
) -> None:
    from app.services import daemon_initializer as daemon_initializer_module

    running_item = create_random_item(db)
    stopped_item = create_random_item(db)
    shared_api_key = "daemon-sync-key"

    for item in (running_item, stopped_item):
        item.socket_host = "127.0.0.1"
        item.socket_port = 9900
        item.api_key = shared_api_key
        item.status = ItemStatus.stopped
        item.socket_connected = False
        db.add(item)
    db.commit()

    restored_calls: list[tuple[str, str]] = []

    class FakeConnection:
        def __init__(self):
            self.callbacks = {}

        def on(self, event, callback):
            self.callbacks[event] = callback

        def is_connected(self):
            return True

        def terminal_list_http(self):
            return {
                "success": True,
                "data": [
                    {
                        "item_uuid": str(running_item.id),
                        "status": "running",
                        "token": "restored-token",
                    }
                ],
            }

    fake_connection = FakeConnection()

    monkeypatch.setattr(
        daemon_initializer_module.connection_manager,
        "get_or_create_connection",
        lambda config: fake_connection,
    )
    monkeypatch.setattr(
        daemon_initializer_module.TerminalService,
        "restore_terminal_session",
        lambda self, *, item_uuid, owner_uuid, daemon_config, token: (
            restored_calls.append((item_uuid, token)) or True
        ),
    )

    daemon_config = DaemonConfig(ip="127.0.0.1", port=9900, api_key=shared_api_key)
    backend_conn_pool.remove_daemon_main_conn_state(shared_api_key)

    assert sync_daemon_connection_state(daemon_config) is True

    with Session(engine) as session:
        running_item_db = session.get(Item, running_item.id)
        stopped_item_db = session.get(Item, stopped_item.id)

    assert running_item_db is not None
    assert running_item_db.status == ItemStatus.running
    assert running_item_db.socket_connected is True
    assert running_item_db.socket_last_connected is not None

    assert stopped_item_db is not None
    assert stopped_item_db.status == ItemStatus.stopped
    assert stopped_item_db.socket_connected is False

    assert restored_calls == [(str(running_item.id), "restored-token")]

    backend_conn_pool.remove_daemon_main_conn_state(shared_api_key)


def test_read_item_reports_daemon_offline_when_connection_state_is_disconnected(
    client,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    from app.core.config import settings

    item = create_random_item(db)
    item.socket_host = "127.0.0.1"
    item.socket_port = 9910
    item.api_key = "daemon-offline-key"
    db.add(item)
    db.commit()

    backend_conn_pool.remove_daemon_main_conn_state(item.api_key)
    backend_conn_pool.create_daemon_main_conn_state(
        item.api_key,
        f"http://{item.socket_host}:{item.socket_port}",
    )

    response = client.get(
        f"{settings.API_V1_STR}/items/{item.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["daemon_online"] is False
    assert payload["daemon_status"] == "disconnected"

    backend_conn_pool.remove_daemon_main_conn_state(item.api_key)
