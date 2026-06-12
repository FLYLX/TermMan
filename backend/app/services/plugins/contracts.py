from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

PluginEnabledPredicate = Callable[[], bool]
PluginRegisterAgentIntegration = Callable[[], None]
PluginIncludeRouter = Callable[[Any], None]
PluginStartup = Callable[[Any], Awaitable[None]]
PluginShutdown = Callable[[Any], Awaitable[None]]


@dataclass(frozen=True)
class PluginEntrypoints:
    register_agent_integration: PluginRegisterAgentIntegration | None = None
    include_router: PluginIncludeRouter | None = None
    startup: PluginStartup | None = None
    shutdown: PluginShutdown | None = None


@dataclass(frozen=True)
class BackendPlugin:
    plugin_id: str
    name: str
    version: str
    description: str = ""
    builtin: bool = True
    category: str = "integration"
    enabled: PluginEnabledPredicate = lambda: True
    entrypoints: PluginEntrypoints = field(default_factory=PluginEntrypoints)

    def is_enabled(self) -> bool:
        return bool(self.enabled())
