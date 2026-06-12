from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import Item

from . import is_terminal_ws_plugin_enabled
from .server import TerminalWebSocketConfig, terminal_ws_manager

terminal_ws_router = APIRouter(prefix="/items", tags=["terminal-websocket"])


class TerminalWebSocketCreateRequest(BaseModel):
    name: str = Field(default="Terminal WebSocket Server", min_length=1, max_length=80)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    token: str | None = Field(default=None, max_length=512)
    heartbeat_interval: float | None = Field(default=None, ge=1.0, le=300.0)
    message_format: Literal["json"] = "json"


def _get_item_for_user(session: SessionDep, current_user: CurrentUser, item_id: uuid.UUID) -> Item:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return item


def _ensure_plugin_enabled() -> None:
    if not is_terminal_ws_plugin_enabled():
        raise HTTPException(status_code=404, detail="Terminal WebSocket plugin is disabled")


def _get_owned_server(server_id: str, current_user: CurrentUser) -> Any:
    server = terminal_ws_manager.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Terminal WebSocket server not found")
    if not current_user.is_superuser and server.config.owner_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return server


def _resolve_port(requested_port: int | None) -> int:
    if requested_port is not None:
        if not settings.TERMINAL_WS_DEFAULT_PORT_START <= requested_port <= settings.TERMINAL_WS_DEFAULT_PORT_END:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Port must be inside TERMINAL_WS_DEFAULT_PORT_START.."
                    "TERMINAL_WS_DEFAULT_PORT_END"
                ),
            )
        return requested_port

    for port in range(settings.TERMINAL_WS_DEFAULT_PORT_START, settings.TERMINAL_WS_DEFAULT_PORT_END + 1):
        if not terminal_ws_manager.port_in_use(port):
            return port
    raise HTTPException(status_code=409, detail="No available terminal WebSocket ports")


def _assert_port_available(port: int, *, exclude_server_id: str | None = None) -> None:
    if terminal_ws_manager.port_in_use(port, exclude_server_id=exclude_server_id):
        raise HTTPException(status_code=409, detail="Port is already used by another terminal WebSocket server")


@terminal_ws_router.get("/{id}/websocket-servers")
def list_item_terminal_websocket_servers(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> dict[str, Any]:
    _ensure_plugin_enabled()
    _get_item_for_user(session, current_user, id)
    return {
        "servers": terminal_ws_manager.list(
            item_id=str(id),
            owner_id=None if current_user.is_superuser else str(current_user.id),
        )
    }


@terminal_ws_router.post("/{id}/websocket-servers")
async def create_item_terminal_websocket_server(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    body: TerminalWebSocketCreateRequest,
) -> dict[str, Any]:
    _ensure_plugin_enabled()
    _get_item_for_user(session, current_user, id)
    server_id = uuid.uuid4().hex
    port = _resolve_port(body.port)
    _assert_port_available(port)
    config = TerminalWebSocketConfig(
        server_id=server_id,
        item_id=str(id),
        owner_id=str(current_user.id),
        name=body.name.strip(),
        host=(body.host or settings.TERMINAL_WS_DEFAULT_HOST).strip(),
        port=port,
        token=body.token.strip() if body.token else "",
        heartbeat_interval=body.heartbeat_interval or settings.TERMINAL_WS_DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        message_format=body.message_format,
    )
    if not config.token:
        config.token = uuid.uuid4().hex + uuid.uuid4().hex
    return await terminal_ws_manager.create_or_replace(config)


@terminal_ws_router.post("/{id}/websocket-servers/{server_id}/start")
async def start_item_terminal_websocket_server(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    server_id: str,
) -> dict[str, Any]:
    _ensure_plugin_enabled()
    _get_item_for_user(session, current_user, id)
    server = _get_owned_server(server_id, current_user)
    if server.config.item_id != str(id):
        raise HTTPException(status_code=404, detail="Terminal WebSocket server not found")
    try:
        status = await terminal_ws_manager.start(server_id)
    except OSError as exc:
        raise HTTPException(status_code=409, detail=f"Failed to bind port: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if status is None:
        raise HTTPException(status_code=404, detail="Terminal WebSocket server not found")
    return status


@terminal_ws_router.post("/{id}/websocket-servers/{server_id}/stop")
async def stop_item_terminal_websocket_server(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    server_id: str,
) -> dict[str, Any]:
    _ensure_plugin_enabled()
    _get_item_for_user(session, current_user, id)
    server = _get_owned_server(server_id, current_user)
    if server.config.item_id != str(id):
        raise HTTPException(status_code=404, detail="Terminal WebSocket server not found")
    status = await terminal_ws_manager.stop(server_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Terminal WebSocket server not found")
    return status


@terminal_ws_router.delete("/{id}/websocket-servers/{server_id}")
async def delete_item_terminal_websocket_server(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    server_id: str,
) -> dict[str, Any]:
    _ensure_plugin_enabled()
    _get_item_for_user(session, current_user, id)
    server = _get_owned_server(server_id, current_user)
    if server.config.item_id != str(id):
        raise HTTPException(status_code=404, detail="Terminal WebSocket server not found")
    deleted = await terminal_ws_manager.delete(server_id)
    return {"success": deleted}


def include_terminal_ws_router(api_router: APIRouter) -> None:
    api_router.include_router(terminal_ws_router)
