from __future__ import annotations

TERMINAL_WS_PLUGIN_ID = "TermPaws.terminal_ws"


def is_terminal_ws_plugin_enabled() -> bool:
    from app.services.plugins import plugin_manager

    plugin = plugin_manager.get(TERMINAL_WS_PLUGIN_ID)
    return bool(plugin and plugin_manager.is_plugin_enabled(plugin))


__all__ = ["TERMINAL_WS_PLUGIN_ID", "is_terminal_ws_plugin_enabled"]
