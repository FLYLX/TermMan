from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services.plugins.contracts import BackendPlugin, PluginEntrypoints
from app.services.plugins.manager import PluginManager


def test_plugin_manager_loads_enabled_builtin_agent_integration(monkeypatch) -> None:
    calls: list[str] = []

    plugin = BackendPlugin(
        plugin_id="test.plugin",
        name="Test Plugin",
        version="builtin",
        enabled=lambda: True,
        entrypoints=PluginEntrypoints(
            register_agent_integration=lambda: calls.append("agent")
        ),
    )

    manager = PluginManager()
    monkeypatch.setattr(manager, "_builtin_plugin_modules", lambda: ("fake.plugin",))
    monkeypatch.setattr(
        "app.services.plugins.manager.importlib.import_module",
        lambda name: SimpleNamespace(get_backend_plugin=lambda: plugin),
    )

    manager.register_agent_integrations()

    assert calls == ["agent"]
    assert manager.enabled_plugins() == [plugin]


def test_plugin_manager_skips_disabled_builtin_plugin(monkeypatch) -> None:
    calls: list[str] = []

    plugin = BackendPlugin(
        plugin_id="test.plugin",
        name="Test Plugin",
        version="builtin",
        enabled=lambda: False,
        entrypoints=PluginEntrypoints(
            register_agent_integration=lambda: calls.append("agent")
        ),
    )

    manager = PluginManager()
    monkeypatch.setattr(manager, "_builtin_plugin_modules", lambda: ("fake.plugin",))
    monkeypatch.setattr(
        "app.services.plugins.manager.importlib.import_module",
        lambda name: SimpleNamespace(get_backend_plugin=lambda: plugin),
    )

    manager.register_agent_integrations()

    assert calls == []
    assert manager.enabled_plugins() == []


def test_plugin_manager_lifecycle_uses_enabled_plugins_and_routes_are_registered(monkeypatch) -> None:
    calls: list[str] = []

    async def startup(app) -> None:
        calls.append(f"startup:{app.name}")

    async def shutdown(app) -> None:
        calls.append(f"shutdown:{app.name}")

    plugin = BackendPlugin(
        plugin_id="test.plugin",
        name="Test Plugin",
        version="builtin",
        enabled=lambda: True,
        entrypoints=PluginEntrypoints(
            include_router=lambda router: calls.append(f"router:{router.name}"),
            startup=startup,
            shutdown=shutdown,
        ),
    )

    manager = PluginManager()
    monkeypatch.setattr(manager, "_builtin_plugin_modules", lambda: ("fake.plugin",))
    monkeypatch.setattr(
        "app.services.plugins.manager.importlib.import_module",
        lambda name: SimpleNamespace(get_backend_plugin=lambda: plugin),
    )
    app = SimpleNamespace(name="app")
    router = SimpleNamespace(name="router")

    manager.include_routers(router)
    asyncio.run(manager.startup(app))
    asyncio.run(manager.shutdown(app))

    assert calls == ["router:router", "startup:app", "shutdown:app"]


def test_plugin_manager_registers_disabled_plugin_routes(monkeypatch) -> None:
    calls: list[str] = []

    plugin = BackendPlugin(
        plugin_id="test.plugin",
        name="Test Plugin",
        version="builtin",
        enabled=lambda: False,
        entrypoints=PluginEntrypoints(
            include_router=lambda router: calls.append(f"router:{router.name}"),
        ),
    )

    manager = PluginManager()
    monkeypatch.setattr(manager, "_builtin_plugin_modules", lambda: ("fake.plugin",))
    monkeypatch.setattr(
        "app.services.plugins.manager.importlib.import_module",
        lambda name: SimpleNamespace(get_backend_plugin=lambda: plugin),
    )
    router = SimpleNamespace(name="router")

    manager.include_routers(router)

    assert calls == ["router:router"]


def test_plugin_manager_persists_plugin_enabled_override(tmp_path, monkeypatch) -> None:
    plugin = BackendPlugin(
        plugin_id="test.plugin",
        name="Test Plugin",
        version="builtin",
        enabled=lambda: True,
    )

    state_path = tmp_path / "plugin_marketplace.json"
    manager = PluginManager(state_path=state_path)
    monkeypatch.setattr(manager, "_builtin_plugin_modules", lambda: ("fake.plugin",))
    monkeypatch.setattr(
        "app.services.plugins.manager.importlib.import_module",
        lambda name: SimpleNamespace(get_backend_plugin=lambda: plugin),
    )

    manager.set_plugin_enabled("test.plugin", False)

    next_manager = PluginManager(state_path=state_path)
    monkeypatch.setattr(next_manager, "_builtin_plugin_modules", lambda: ("fake.plugin",))
    monkeypatch.setattr(
        "app.services.plugins.manager.importlib.import_module",
        lambda name: SimpleNamespace(get_backend_plugin=lambda: plugin),
    )

    assert next_manager.enabled_plugins() == []
    assert next_manager.catalog()[0]["enabled"] is False
