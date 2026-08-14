from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qsl
from uuid import uuid4

from app.services.daemon_initializer import socket_pool_facade
from app.services.socket_pool.event_bus import SubscriptionEvent, SubscriptionEventType
from app.services.socket_pool.subscription_center import subscription_center

logger = logging.getLogger(__name__)

try:
    import websockets

    try:
        from websockets.asyncio.server import (
            ServerConnection as WebSocketServerProtocol,
        )
    except Exception:  # pragma: no cover - compatibility with older websockets
        from websockets.legacy.server import WebSocketServerProtocol
except Exception:  # pragma: no cover - import fallback for minimal envs
    websockets = None
    WebSocketServerProtocol = Any  # type: ignore[misc, assignment]


TERMINAL_WS_PROTOCOL_VERSION = 1
TerminalWsMessageFormat = Literal["json"]


@dataclass
class TerminalWebSocketClient:
    client_id: str
    websocket: WebSocketServerProtocol
    subscription_id: str = ""


@dataclass
class TerminalWebSocketConfig:
    server_id: str
    item_id: str
    owner_id: str
    name: str
    host: str = "0.0.0.0"
    port: int = 7100
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    heartbeat_interval: float = 30.0
    message_format: TerminalWsMessageFormat = "json"


class TerminalWebSocketServer:
    def __init__(self, config: TerminalWebSocketConfig) -> None:
        self.config = config
        self._server: Any | None = None
        self._clients: dict[str, TerminalWebSocketClient] = {}
        self._clients_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    @property
    def public_url(self) -> str:
        return f"ws://{self.config.host}:{self.config.port}/?token={self.config.token}"

    def status(self) -> dict[str, Any]:
        return {
            "server_id": self.config.server_id,
            "item_id": self.config.item_id,
            "name": self.config.name,
            "host": self.config.host,
            "port": self.config.port,
            "token": self.config.token,
            "heartbeat_interval": self.config.heartbeat_interval,
            "message_format": self.config.message_format,
            "running": self.is_running,
            "client_count": len(self._clients),
            "url": self.public_url,
        }

    async def start(self) -> None:
        if self._started:
            return
        if websockets is None:
            raise RuntimeError("websockets package is unavailable")
        if not self.config.token:
            raise RuntimeError("token is required")

        self._loop = asyncio.get_running_loop()
        self._server = await websockets.serve(
            self._handle_client,
            self.config.host,
            self.config.port,
            ping_interval=self.config.heartbeat_interval,
            ping_timeout=max(5.0, self.config.heartbeat_interval * 2),
        )
        self._started = True
        logger.info(
            "[TerminalWS] %s listening on ws://%s:%s item=%s format=%s heartbeat=%ss",
            self.config.name,
            self.config.host,
            self.config.port,
            self.config.item_id,
            self.config.message_format,
            self.config.heartbeat_interval,
        )

    async def stop(self) -> None:
        if not self._started:
            return

        async with self._clients_lock:
            clients = list(self._clients.values())

        for client in clients:
            await self._disconnect_client(client)

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        self._started = False
        self._loop = None
        logger.info("[TerminalWS] %s stopped", self.config.name)

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        client = TerminalWebSocketClient(client_id=uuid4().hex, websocket=websocket)
        try:
            token = self._extract_token(websocket)
            if not self._token_is_valid(token):
                await self._send(websocket, self._error("auth_failed", "Invalid token"))
                await websocket.close(code=4401, reason="Invalid token")
                return

            await self._register_client(client)
            await self._send(
                websocket,
                {
                    "type": "hello",
                    "name": self.config.name,
                    "version": TERMINAL_WS_PROTOCOL_VERSION,
                    "client_id": client.client_id,
                    "item_id": self.config.item_id,
                    "message_format": self.config.message_format,
                    "heartbeat_interval": self.config.heartbeat_interval,
                },
            )

            async for raw_message in websocket:
                await self._handle_message(client, raw_message)
        except Exception as exc:
            logger.debug("[TerminalWS] Client %s disconnected: %s", client.client_id, exc)
        finally:
            await self._disconnect_client(client)

    def _extract_token(self, websocket: WebSocketServerProtocol) -> str:
        request = getattr(websocket, "request", None)
        request_headers = getattr(websocket, "request_headers", None)
        if request_headers is None and request is not None:
            request_headers = getattr(request, "headers", {})
        request_headers = request_headers or {}
        auth_header = str(request_headers.get("Authorization", "") or "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()

        token_header = str(request_headers.get("X-TermPaws-Token", "") or "").strip()
        if token_header:
            return token_header

        path = str(getattr(websocket, "path", "") or getattr(request, "path", "") or "")
        if "?" not in path:
            return ""
        query = path.split("?", 1)[1]
        for key, value in parse_qsl(query, keep_blank_values=True):
            if key == "token":
                return value.strip()
        return ""

    def _token_is_valid(self, token: str) -> bool:
        return bool(self.config.token) and secrets.compare_digest(token, self.config.token)

    async def _register_client(self, client: TerminalWebSocketClient) -> None:
        subscriber_id = subscription_center.subscribe(
            item_uuid=self.config.item_id,
            callback=self._make_stream_callback(client),
            subscriber_type="terminal_ws",
            event_types=[SubscriptionEventType.STREAM],
            subscriber_id=f"terminal_ws_{self.config.server_id}_{client.client_id}",
        )
        client.subscription_id = subscriber_id
        async with self._clients_lock:
            self._clients[client.client_id] = client

    async def _disconnect_client(self, client: TerminalWebSocketClient) -> None:
        if client.subscription_id:
            subscription_center.unsubscribe(client.subscription_id)
            client.subscription_id = ""
        async with self._clients_lock:
            self._clients.pop(client.client_id, None)
        try:
            await client.websocket.close()
        except Exception:
            pass

    async def _handle_message(
        self,
        client: TerminalWebSocketClient,
        raw_message: str | bytes,
    ) -> None:
        try:
            message = json.loads(raw_message.decode() if isinstance(raw_message, bytes) else raw_message)
        except Exception:
            await self._send(client.websocket, self._error("bad_json", "Message must be JSON"))
            return

        if not isinstance(message, dict):
            await self._send(client.websocket, self._error("bad_message", "Message must be an object"))
            return

        message_type = str(message.get("type") or "").strip()
        if message_type == "ping":
            await self._send(client.websocket, {"type": "pong", "ts": self._timestamp()})
            return
        if message_type == "write":
            await self._write(client, message)
            return
        if message_type in {"subscribe", "unsubscribe"}:
            await self._send(
                client.websocket,
                {
                    "type": "subscribed" if message_type == "subscribe" else "unsubscribed",
                    "item_id": self.config.item_id,
                },
            )
            return

        await self._send(client.websocket, self._error("unknown_type", f"Unknown type: {message_type}"))

    def _make_stream_callback(self, client: TerminalWebSocketClient) -> Callable[[SubscriptionEvent], None]:
        def callback(event: SubscriptionEvent) -> None:
            payload = self._stream_payload(event.item_uuid, event.data, source="terminal")
            self._schedule_send(client.websocket, payload)

        return callback

    async def _write(
        self,
        client: TerminalWebSocketClient,
        message: dict[str, Any],
    ) -> None:
        command = str(message.get("command") or message.get("stdin") or "")
        if not command:
            await self._send(client.websocket, self._error("missing_command", "write requires command or stdin"))
            return

        success = socket_pool_facade.write_to_item(self.config.item_id, command, source="terminal_ws")
        await self._send(
            client.websocket,
            {
                "type": "write_result",
                "item_id": self.config.item_id,
                "success": success,
            },
        )

    def _schedule_send(
        self,
        websocket: WebSocketServerProtocol,
        payload: dict[str, Any],
    ) -> None:
        self._schedule_coro(self._send(websocket, payload))

    def _schedule_coro(self, coro: Any) -> None:
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("[TerminalWS] No running loop for stream dispatch")
            coro.close()
            return
        loop.create_task(coro)

    async def _send(
        self,
        websocket: WebSocketServerProtocol,
        payload: dict[str, Any],
    ) -> None:
        try:
            await websocket.send(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            logger.debug("[TerminalWS] Send failed: %s", exc)

    def _stream_payload(
        self,
        item_id: str,
        data: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        stdout = str(data.get("stdout") or "")
        stderr = str(data.get("stderr") or "")
        stdin = str(data.get("stdin") or "")
        return {
            "type": "stream",
            "item_id": item_id,
            "stdout": stdout,
            "stderr": stderr,
            "stdin": stdin,
            "stream": self._stream_name(stdout=stdout, stderr=stderr, stdin=stdin),
            "source": str(data.get("source") or source),
            "ts": self._timestamp(),
        }

    @staticmethod
    def _stream_name(*, stdout: str, stderr: str, stdin: str) -> str:
        if stdin and not stdout and not stderr:
            return "stdin"
        if stderr and not stdout:
            return "stderr"
        if stdout and not stderr:
            return "stdout"
        return "mixed"

    @staticmethod
    def _error(code: str, message: str) -> dict[str, str]:
        return {
            "type": "error",
            "code": code,
            "message": message,
        }

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()


class TerminalWebSocketManager:
    def __init__(self) -> None:
        self._servers: dict[str, TerminalWebSocketServer] = {}
        self._lock = asyncio.Lock()

    async def create_or_replace(self, config: TerminalWebSocketConfig) -> dict[str, Any]:
        async with self._lock:
            existing = self._servers.get(config.server_id)
            if existing is not None:
                await existing.stop()
            server = TerminalWebSocketServer(config)
            self._servers[config.server_id] = server
            return server.status()

    async def start(self, server_id: str) -> dict[str, Any] | None:
        async with self._lock:
            server = self._servers.get(server_id)
            if server is None:
                return None
            await server.start()
            return server.status()

    async def stop(self, server_id: str) -> dict[str, Any] | None:
        async with self._lock:
            server = self._servers.get(server_id)
            if server is None:
                return None
            await server.stop()
            return server.status()

    async def delete(self, server_id: str) -> bool:
        async with self._lock:
            server = self._servers.pop(server_id, None)
            if server is None:
                return False
            await server.stop()
            return True

    async def shutdown(self) -> None:
        async with self._lock:
            servers = list(self._servers.values())
        for server in servers:
            await server.stop()

    def get(self, server_id: str) -> TerminalWebSocketServer | None:
        return self._servers.get(server_id)

    def list(self, *, item_id: str | None = None, owner_id: str | None = None) -> list[dict[str, Any]]:
        servers = list(self._servers.values())
        if item_id is not None:
            servers = [server for server in servers if server.config.item_id == item_id]
        if owner_id is not None:
            servers = [server for server in servers if server.config.owner_id == owner_id]
        return [server.status() for server in servers]

    def port_in_use(self, port: int, *, exclude_server_id: str | None = None) -> bool:
        return any(
            server.config.port == port and server.config.server_id != exclude_server_id
            for server in self._servers.values()
        )


terminal_ws_manager = TerminalWebSocketManager()
