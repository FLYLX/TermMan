from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.plugins import plugin_manager


def test_list_builtin_plugins(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(plugin_manager, "_state_path", tmp_path / "plugins.json")
    monkeypatch.setattr(plugin_manager, "_state_loaded", False)
    monkeypatch.setattr(plugin_manager, "_enabled_overrides", {})
    plugin_manager.reload()

    response = client.get(
        f"{settings.API_V1_STR}/plugins/",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    plugin_ids = {plugin["plugin_id"] for plugin in payload["data"]}
    assert "termman.robot" in plugin_ids
    assert "termman.terminal_ws" in plugin_ids


def test_superuser_can_toggle_builtin_plugin(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(plugin_manager, "_state_path", tmp_path / "plugins.json")
    monkeypatch.setattr(plugin_manager, "_state_loaded", False)
    monkeypatch.setattr(plugin_manager, "_enabled_overrides", {})
    plugin_manager.reload()

    response = client.patch(
        f"{settings.API_V1_STR}/plugins/termman.robot",
        headers=superuser_token_headers,
        json={"enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert plugin_manager.get("termman.robot") not in plugin_manager.enabled_plugins()

    from app.plugins.robot import is_robot_plugin_enabled

    assert is_robot_plugin_enabled() is False
