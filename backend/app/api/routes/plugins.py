from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.services.plugins import plugin_manager

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginPublic(BaseModel):
    plugin_id: str
    name: str
    version: str
    description: str
    builtin: bool
    category: str
    enabled: bool
    default_enabled: bool
    configurable: bool
    capabilities: list[str]


class PluginListResponse(BaseModel):
    data: list[PluginPublic]
    count: int


class PluginUpdateBody(BaseModel):
    enabled: bool


def _require_superuser(current_user: CurrentUser) -> None:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only superusers can manage plugins")


def _plugin_payload(plugin_id: str) -> dict[str, Any]:
    plugin = plugin_manager.get(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin_manager.serialize_plugin(plugin)


@router.get("/", response_model=PluginListResponse)
def list_plugins(current_user: CurrentUser) -> PluginListResponse:
    _ = current_user
    data = [PluginPublic.model_validate(plugin) for plugin in plugin_manager.catalog()]
    return PluginListResponse(data=data, count=len(data))


@router.get("/{plugin_id:path}", response_model=PluginPublic)
def get_plugin(plugin_id: str, current_user: CurrentUser) -> PluginPublic:
    _ = current_user
    return PluginPublic.model_validate(_plugin_payload(plugin_id))


@router.patch("/{plugin_id:path}", response_model=PluginPublic)
async def update_plugin(
    plugin_id: str,
    body: PluginUpdateBody,
    request: Request,
    current_user: CurrentUser,
) -> PluginPublic:
    _require_superuser(current_user)
    try:
        plugin = plugin_manager.set_plugin_enabled(plugin_id, body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    entrypoint = (
        plugin.entrypoints.startup if body.enabled else plugin.entrypoints.shutdown
    )
    if entrypoint is not None:
        await entrypoint(request.app)
    plugin_manager.reload()
    return PluginPublic.model_validate(_plugin_payload(plugin_id))


@router.post("/reload", response_model=PluginListResponse)
def reload_plugins(current_user: CurrentUser) -> PluginListResponse:
    _require_superuser(current_user)
    plugin_manager.reload()
    data = [PluginPublic.model_validate(plugin) for plugin in plugin_manager.catalog()]
    return PluginListResponse(data=data, count=len(data))
