from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from fastapi import APIRouter, Request, Response, WebSocket

from app.core.config import settings

robot_bridge_proxy_router = APIRouter(prefix="/robot-bridge", tags=["robot-bridge"])

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_WS_HANDSHAKE_HEADERS = {
    "host",
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
    *_HOP_BY_HOP_HEADERS,
}


def _strip_public_route(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "r" and parts[1]:
        return "/".join(parts[2:])
    return path


def _target_url(path: str, query: str, *, websocket: bool = False) -> str:
    base = settings.ROBOT_BRIDGE_URL.rstrip("/")
    parts = urlsplit(base)
    scheme = parts.scheme
    if websocket:
        scheme = "wss" if scheme == "https" else "ws"

    path = _strip_public_route(path)
    base_path = parts.path.rstrip("/")
    target_path = f"{base_path}/{path}".replace("//", "/")
    if not target_path.startswith("/"):
        target_path = f"/{target_path}"
    return urlunsplit((scheme, parts.netloc, target_path, query, ""))


def _filtered_http_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "host"
    }


def _filtered_ws_headers(websocket: WebSocket) -> list[tuple[str, str]]:
    filtered: list[tuple[str, str]] = []
    for raw_key, raw_value in websocket.headers.raw:
        key = raw_key.decode("latin-1")
        if key.lower() in _WS_HANDSHAKE_HEADERS:
            continue
        filtered.append((key, raw_value.decode("latin-1")))
    return filtered


def _websockets_header_kwargs(headers: list[tuple[str, str]]) -> dict:
    parameters = inspect.signature(websockets.connect).parameters
    if "additional_headers" in parameters:
        return {"additional_headers": headers}
    return {"extra_headers": headers}


@robot_bridge_proxy_router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_robot_bridge_http(path: str, request: Request) -> Response:
    target = _target_url(path, request.url.query)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            request.method,
            target,
            headers=_filtered_http_headers(request.headers),
            content=await request.body(),
        )
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=_filtered_http_headers(response.headers),
    )


@robot_bridge_proxy_router.websocket("/{path:path}")
async def proxy_robot_bridge_websocket(path: str, websocket: WebSocket) -> None:
    target = _target_url(path, websocket.url.query, websocket=True)
    await websocket.accept()

    try:
        async with websockets.connect(
            target,
            **_websockets_header_kwargs(_filtered_ws_headers(websocket)),
        ) as bridge_ws:

            async def client_to_bridge() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        await bridge_ws.close()
                        return
                    if message.get("text") is not None:
                        await bridge_ws.send(message["text"])
                    elif message.get("bytes") is not None:
                        await bridge_ws.send(message["bytes"])

            async def bridge_to_client() -> None:
                async for message in bridge_ws:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = {
                asyncio.create_task(client_to_bridge()),
                asyncio.create_task(bridge_to_client()),
            }
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except Exception:
        await websocket.close(code=1011)
