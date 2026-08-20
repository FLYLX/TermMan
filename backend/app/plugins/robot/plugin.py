from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

from app.core.config import settings
from app.services.plugins.contracts import BackendPlugin, PluginEntrypoints

logger = logging.getLogger(__name__)

_bridge_router_included = False
_embedded_bridge_started = False


def is_enabled() -> bool:
    return bool(settings.ROBOT_PLUGIN_ENABLED)


def include_router(api_router: APIRouter) -> None:
    from .api import router

    api_router.include_router(router)


def register_agent_integration() -> None:
    from app.plugins.robot.agent.integration import register_robot_agent_integration

    register_robot_agent_integration()


async def startup(app: FastAPI) -> None:
    global _bridge_router_included, _embedded_bridge_started

    from app.plugins.robot.bridge.embedded import (
        get_bridge_router,
        init_embedded_bridge,
        set_bridge_app,
        start_embedded_bridge,
    )

    logger.info("[RobotPlugin] Initializing embedded robot bridge...")
    set_bridge_app(app)
    init_embedded_bridge()
    bridge_router = get_bridge_router()
    if bridge_router and not _bridge_router_included:
        app.include_router(bridge_router)
        _bridge_router_included = True
        logger.info("[RobotPlugin] Robot bridge router included")
    if bridge_router:
        logger.info("[RobotPlugin] Robot bridge initialized")
    await start_embedded_bridge()
    _embedded_bridge_started = True


async def shutdown(app: FastAPI) -> None:
    global _embedded_bridge_started

    _ = app
    if not _embedded_bridge_started:
        return

    from app.plugins.robot.bridge.embedded import stop_embedded_bridge

    await stop_embedded_bridge()
    _embedded_bridge_started = False


def get_backend_plugin() -> BackendPlugin:
    return BackendPlugin(
        plugin_id="TermPaws.robot",
        name="Robot",
        version="builtin",
        description="Optional QQ robot server integration through OneBot V11 connectors and MCP.",
        builtin=True,
        category="messaging",
        enabled=is_enabled,
        entrypoints=PluginEntrypoints(
            register_agent_integration=register_agent_integration,
            include_router=include_router,
            startup=startup,
            shutdown=shutdown,
        ),
    )
