from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import BACKEND_DIR

from .contracts import BackendPlugin

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self, *, state_path: Path | None = None) -> None:
        self._plugins: dict[str, BackendPlugin] = {}
        self._builtin_loaded = False
        self._state_path = state_path or BACKEND_DIR.parent / ".runtime" / "plugin_marketplace.json"
        self._state_loaded = False
        self._enabled_overrides: dict[str, bool] = {}

    def load_builtin_plugins(self, *, force: bool = False) -> None:
        if self._builtin_loaded and not force:
            return
        if force:
            self._plugins.clear()
        self._builtin_loaded = True

        for module_name in self._builtin_plugin_modules():
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                logger.debug("[PluginManager] Builtin plugin module unavailable: %s", exc)
                continue

            get_plugin = getattr(module, "get_backend_plugin", None)
            if not callable(get_plugin):
                logger.debug(
                    "[PluginManager] Builtin plugin %s has no get_backend_plugin",
                    module_name,
                )
                continue

            plugin = get_plugin()
            self.register(plugin)

    def reload(self) -> None:
        importlib.invalidate_caches()
        self.load_builtin_plugins(force=True)
        try:
            from app.services.agent.integrations import reload_agent_integrations
        except Exception as exc:
            logger.debug("[PluginManager] Agent integration reload unavailable: %s", exc)
        else:
            reload_agent_integrations(reload_plugins=False)

    def register(self, plugin: BackendPlugin) -> None:
        if not plugin.plugin_id:
            raise ValueError("Plugin id is required")
        self._plugins[plugin.plugin_id] = plugin

    def is_plugin_enabled(self, plugin: BackendPlugin) -> bool:
        self._load_state()
        if plugin.plugin_id in self._enabled_overrides:
            return self._enabled_overrides[plugin.plugin_id]
        return plugin.is_enabled()

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> BackendPlugin:
        plugin = self.get(plugin_id)
        if plugin is None:
            raise KeyError(plugin_id)
        self._load_state()
        self._enabled_overrides[plugin_id] = enabled
        self._save_state()
        return plugin

    def get(self, plugin_id: str) -> BackendPlugin | None:
        self.load_builtin_plugins()
        return self._plugins.get(plugin_id)

    def all(self) -> list[BackendPlugin]:
        self.load_builtin_plugins()
        return list(self._plugins.values())

    def enabled_plugins(self) -> list[BackendPlugin]:
        return [plugin for plugin in self.all() if self.is_plugin_enabled(plugin)]

    def catalog(self) -> list[dict[str, object]]:
        return [self.serialize_plugin(plugin) for plugin in self.all()]

    def serialize_plugin(self, plugin: BackendPlugin) -> dict[str, object]:
        return {
            "plugin_id": plugin.plugin_id,
            "name": plugin.name,
            "version": plugin.version,
            "description": plugin.description,
            "builtin": plugin.builtin,
            "category": plugin.category,
            "enabled": self.is_plugin_enabled(plugin),
            "default_enabled": plugin.is_enabled(),
            "configurable": True,
            "capabilities": self._capabilities(plugin),
        }

    def register_agent_integrations(self) -> None:
        for plugin in self.enabled_plugins():
            register = plugin.entrypoints.register_agent_integration
            if register is None:
                continue
            register()

    def include_routers(self, api_router: APIRouter) -> None:
        for plugin in self.all():
            include_router = plugin.entrypoints.include_router
            if include_router is None:
                continue
            include_router(api_router)

    async def startup(self, app: FastAPI) -> None:
        for plugin in self.enabled_plugins():
            startup = plugin.entrypoints.startup
            if startup is None:
                continue
            await startup(app)

    async def shutdown(self, app: FastAPI) -> None:
        for plugin in reversed(self.enabled_plugins()):
            shutdown = plugin.entrypoints.shutdown
            if shutdown is None:
                continue
            await shutdown(app)

    @staticmethod
    def _builtin_plugin_modules() -> Iterable[str]:
        return (
            "app.plugins.robot.plugin",
            "app.plugins.terminal_ws.plugin",
        )

    def _load_state(self) -> None:
        if self._state_loaded:
            return
        self._state_loaded = True
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning("[PluginManager] Failed to read plugin state: %s", exc)
            return

        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, dict):
            return
        for plugin_id, state in plugins.items():
            if not isinstance(plugin_id, str) or not isinstance(state, dict):
                continue
            enabled = state.get("enabled")
            if isinstance(enabled, bool):
                self._enabled_overrides[plugin_id] = enabled

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "plugins": {
                plugin_id: {"enabled": enabled}
                for plugin_id, enabled in sorted(self._enabled_overrides.items())
            },
        }
        self._state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _capabilities(plugin: BackendPlugin) -> list[str]:
        capabilities: list[str] = []
        if plugin.entrypoints.register_agent_integration is not None:
            capabilities.append("agent")
        if plugin.entrypoints.include_router is not None:
            capabilities.append("api")
        if plugin.entrypoints.startup is not None:
            capabilities.append("startup")
        if plugin.entrypoints.shutdown is not None:
            capabilities.append("shutdown")
        return capabilities


plugin_manager = PluginManager()
