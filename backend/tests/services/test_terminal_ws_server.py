from __future__ import annotations

import asyncio
import json

from app.plugins.terminal_ws.server import (
    TerminalWebSocketClient,
    TerminalWebSocketConfig,
    TerminalWebSocketManager,
    TerminalWebSocketServer,
)


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False
        self.request_headers = {}
        self.path = "/?token=test-token"

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self, *args, **kwargs) -> None:
        self.closed = True


def _config() -> TerminalWebSocketConfig:
    return TerminalWebSocketConfig(
        server_id="server-1",
        item_id="item-1",
        owner_id="user-1",
        name="Item WS",
        host="127.0.0.1",
        port=7101,
        token="test-token",
    )


def _decoded(websocket: FakeWebSocket) -> list[dict]:
    return [json.loads(message) for message in websocket.sent]


def test_terminal_ws_write_targets_bound_item(monkeypatch) -> None:
    server = TerminalWebSocketServer(_config())
    websocket = FakeWebSocket()
    client = TerminalWebSocketClient(client_id="client-1", websocket=websocket)
    writes: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        "app.plugins.terminal_ws.server.socket_pool_facade.write_to_item",
        lambda item_id, command, *, source="backend": writes.append((item_id, command, source)) or True,
    )

    asyncio.run(
        server._handle_message(
            client,
            json.dumps(
                {
                    "type": "write",
                    "item_id": "ignored-item",
                    "command": "ls\n",
                }
            ),
        )
    )

    assert writes == [("item-1", "ls\n", "terminal_ws")]
    assert _decoded(websocket)[-1] == {
        "type": "write_result",
        "item_id": "item-1",
        "success": True,
    }


def test_terminal_ws_registers_item_subscription_on_client_connect(monkeypatch) -> None:
    server = TerminalWebSocketServer(_config())
    websocket = FakeWebSocket()
    client = TerminalWebSocketClient(client_id="client-1", websocket=websocket)
    subscriptions: list[dict] = []

    def fake_subscribe(**kwargs):
        subscriptions.append(kwargs)
        return "sub-1"

    monkeypatch.setattr(
        "app.plugins.terminal_ws.server.subscription_center.subscribe",
        fake_subscribe,
    )

    asyncio.run(server._register_client(client))

    assert client.subscription_id == "sub-1"
    assert subscriptions[0]["item_uuid"] == "item-1"
    assert subscriptions[0]["subscriber_type"] == "terminal_ws"


def test_terminal_ws_stream_callback_sends_payload() -> None:
    server = TerminalWebSocketServer(_config())
    websocket = FakeWebSocket()
    client = TerminalWebSocketClient(client_id="client-1", websocket=websocket)

    async def run_callback() -> None:
        server._loop = asyncio.get_running_loop()
        callback = server._make_stream_callback(client)
        event = type(
            "Event",
            (),
            {"item_uuid": "item-1", "data": {"stdout": "out", "source": "terminal"}},
        )()
        callback(event)
        await asyncio.sleep(0)

    asyncio.run(run_callback())

    assert _decoded(websocket)[-1]["stdout"] == "out"
    assert _decoded(websocket)[-1]["source"] == "terminal"


def test_terminal_ws_token_accepts_query_header_or_bearer() -> None:
    server = TerminalWebSocketServer(_config())

    query_ws = FakeWebSocket()
    query_ws.path = "/terminal?token=test-token"
    assert server._token_is_valid(server._extract_token(query_ws))

    header_ws = FakeWebSocket()
    header_ws.path = "/terminal"
    header_ws.request_headers = {"X-TermPaws-Token": "test-token"}
    assert server._token_is_valid(server._extract_token(header_ws))

    bearer_ws = FakeWebSocket()
    bearer_ws.path = "/terminal"
    bearer_ws.request_headers = {"Authorization": "Bearer test-token"}
    assert server._token_is_valid(server._extract_token(bearer_ws))


def test_terminal_ws_manager_lists_by_item_and_owner() -> None:
    manager = TerminalWebSocketManager()

    async def run_manager() -> None:
        await manager.create_or_replace(_config())

    asyncio.run(run_manager())

    assert len(manager.list(item_id="item-1", owner_id="user-1")) == 1
    assert manager.list(item_id="item-2", owner_id="user-1") == []
    assert manager.list(item_id="item-1", owner_id="user-2") == []
    assert manager.port_in_use(7101)
