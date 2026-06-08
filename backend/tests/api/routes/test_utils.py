from fastapi.testclient import TestClient

from app.core.config import settings


def test_backend_runtime_stats_requires_superuser(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/utils/backend-runtime/",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403


def test_backend_runtime_stats_returns_payload_for_superuser(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/utils/backend-runtime/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200

    content = response.json()
    assert content["service"] == "backend"
    assert isinstance(content["sampled_at"], int)
    assert isinstance(content["aggregate"], dict)
    assert isinstance(content["current_process"], dict)
    assert isinstance(content["processes"], list)
    assert "cpu_model" in content
    assert "cpu_frequency_mhz" in content
    assert "memory_total_bytes" in content
    assert "memory_used_bytes" in content
    assert "memory_percent" in content
    assert isinstance(content["ip_addresses"], list)
    assert content["current_process"]["pid"] > 0
    assert content["aggregate"]["process_count"] >= 1


def test_termman_runtime_stats_requires_superuser(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/utils/termman-runtime/",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403


def test_termman_runtime_stats_returns_backend_service(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    from app.api.routes import utils as utils_route

    monkeypatch.setattr(
        utils_route.robot_bridge_client,
        "get_health",
        lambda timeout=5.0: {},
    )

    response = client.get(
        f"{settings.API_V1_STR}/utils/termman-runtime/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200

    content = response.json()
    assert isinstance(content["sampled_at"], int)
    assert isinstance(content["services"], list)
    assert content["totals"]["service_count"] >= 1

    backend_service = next(
        service for service in content["services"] if service["service"] == "backend"
    )
    assert backend_service["status"] == "ok"
    assert backend_service["runtime"]["aggregate"]["process_count"] >= 1
