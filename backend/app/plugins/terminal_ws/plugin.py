from __future__ import annotations

from fastapi import FastAPI

from app.plugins.terminal_ws.api import include_terminal_ws_router
from app.plugins.terminal_ws.server import terminal_ws_manager
from app.services.plugins.contracts import BackendPlugin, PluginEntrypoints


def is_enabled() -> bool:
    # Default state for the built-in marketplace. Runtime overrides live in PluginManager.
    return True


async def shutdown(app: FastAPI) -> None:
    _ = app
    await terminal_ws_manager.shutdown()


def get_backend_plugin() -> BackendPlugin:
    return BackendPlugin(
        plugin_id="TermPaws.terminal_ws",
        name="Terminal WebSocket Servers",
        version="builtin",
        description="Let users create per-terminal WebSocket servers from the Web UI.",
        builtin=True,
        category="terminal",
        enabled=is_enabled,
        entrypoints=PluginEntrypoints(
            include_router=include_terminal_ws_router,
            shutdown=shutdown,
        ),
    )
