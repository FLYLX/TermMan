from __future__ import annotations

import logging

from .contracts import AgentIntegration

logger = logging.getLogger(__name__)

_integrations: dict[str, AgentIntegration] = {}
_plugin_integrations_loaded = False


def register_agent_integration(integration: AgentIntegration) -> None:
    if not integration.name:
        raise ValueError("Agent integration name is required")
    _integrations[integration.name] = integration


def get_agent_integration(name: str) -> AgentIntegration | None:
    load_agent_integrations()
    return _integrations.get(name)


def get_agent_integrations() -> list[AgentIntegration]:
    load_agent_integrations()
    return list(_integrations.values())


def load_agent_integrations() -> None:
    global _plugin_integrations_loaded
    if _plugin_integrations_loaded:
        return

    _plugin_integrations_loaded = True
    try:
        from app.services.plugins import plugin_manager
    except Exception as exc:
        logger.debug("[AgentIntegration] Plugin manager unavailable: %s", exc)
        return

    plugin_manager.register_agent_integrations()


def reload_agent_integrations(*, reload_plugins: bool = True) -> None:
    global _plugin_integrations_loaded
    _integrations.clear()
    _plugin_integrations_loaded = False
    if reload_plugins:
        try:
            from app.services.plugins import plugin_manager
        except Exception as exc:
            logger.debug("[AgentIntegration] Plugin manager reload unavailable: %s", exc)
        else:
            plugin_manager.reload()
    load_agent_integrations()
