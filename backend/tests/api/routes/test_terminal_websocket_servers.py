import asyncio

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.plugins.terminal_ws.server import terminal_ws_manager
from tests.utils.item import create_random_item


def test_create_and_list_item_terminal_websocket_server(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    item = create_random_item(db)

    response = client.post(
        f"{settings.API_V1_STR}/items/{item.id}/websocket-servers",
        headers=superuser_token_headers,
        json={
            "name": "External Tail",
            "host": "0.0.0.0",
            "port": 7105,
            "token": "custom-token",
            "heartbeat_interval": 15,
            "message_format": "json",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "External Tail"
    assert payload["item_id"] == str(item.id)
    assert payload["port"] == 7105
    assert payload["token"] == "custom-token"
    assert payload["running"] is False

    list_response = client.get(
        f"{settings.API_V1_STR}/items/{item.id}/websocket-servers",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert len(list_response.json()["servers"]) == 1

    asyncio.run(terminal_ws_manager.delete(payload["server_id"]))


def test_create_item_terminal_websocket_server_rejects_used_port(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    item = create_random_item(db)
    body = {
        "name": "External Tail",
        "host": "0.0.0.0",
        "port": 7106,
    }

    first_response = client.post(
        f"{settings.API_V1_STR}/items/{item.id}/websocket-servers",
        headers=superuser_token_headers,
        json=body,
    )
    assert first_response.status_code == 200

    second_response = client.post(
        f"{settings.API_V1_STR}/items/{item.id}/websocket-servers",
        headers=superuser_token_headers,
        json=body,
    )
    assert second_response.status_code == 409

    asyncio.run(terminal_ws_manager.delete(first_response.json()["server_id"]))
