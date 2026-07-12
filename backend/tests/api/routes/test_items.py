import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.utils.item import create_random_item


def test_create_item(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"title": "Foo", "description": "Fighters"}
    response = client.post(
        f"{settings.API_V1_STR}/items/",
        headers=superuser_token_headers,
        json=data,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["title"] == data["title"]
    assert content["description"] == data["description"]
    assert "id" in content
    assert "owner_id" in content
    # 测试新添加的字段
    assert "status" in content
    assert "socket_host" in content
    assert "socket_port" in content
    assert "socket_connected" in content
    assert "socket_last_connected" in content
    assert "api_key" in content
    assert "command" in content
    assert "working_directory" in content
    assert "input_filter_enabled" in content
    assert "input_filter_rules" in content
    assert "output_filter_enabled" in content
    assert "output_filter_rules" in content


def test_read_item(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    response = client.get(
        f"{settings.API_V1_STR}/items/{item.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["title"] == item.title
    assert content["description"] == item.description
    assert content["id"] == str(item.id)
    assert content["owner_id"] == str(item.owner_id)
    # 测试新添加的字段
    assert content["status"] == item.status
    assert content["socket_host"] == item.socket_host
    assert content["socket_port"] == item.socket_port
    assert content["socket_connected"] == item.socket_connected
    assert content["socket_last_connected"] == item.socket_last_connected
    assert content["api_key"] == item.api_key
    assert content["command"] == item.command
    assert content["working_directory"] == item.working_directory
    assert content["input_filter_enabled"] == item.input_filter_enabled
    assert content["input_filter_rules"] == item.input_filter_rules
    assert content["output_filter_enabled"] == item.output_filter_enabled
    assert content["output_filter_rules"] == item.output_filter_rules
    assert "daemon_online" in content
    assert "daemon_status" in content
    assert "browser_count" in content
    assert "backend_connected" in content


def test_read_item_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/items/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Item not found"


def test_read_item_not_enough_permissions(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    response = client.get(
        f"{settings.API_V1_STR}/items/{item.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    content = response.json()
    assert content["detail"] == "Not enough permissions"



def test_list_item_jobs_returns_empty_when_daemon_not_connected(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    response = client.get(
        f"{settings.API_V1_STR}/items/{item.id}/jobs",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["success"] is True
    assert content["item_uuid"] == str(item.id)
    assert content["jobs"] == []
    assert content["count"] == 0
    assert content["daemon_online"] is False
    assert content["error"] == "Daemon is not connected"


def test_cancel_item_job_requires_daemon_connection(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    response = client.post(
        f"{settings.API_V1_STR}/items/{item.id}/jobs/job-1/cancel",
        headers=superuser_token_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Daemon is not connected"


def test_cancel_item_job_clears_agent_terminal_job_lock(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import items as items_routes
    from app.services.agent.session import RUN_JOB_TOOL_NAME, agent_session_manager

    item = create_random_item(db)
    item.socket_host = "127.0.0.1"
    item.socket_port = 19001
    db.add(item)
    db.commit()
    db.refresh(item)

    class FakeDaemonState:
        def is_connected(self):
            return True

    class FakeBackendConnPool:
        def get_daemon_main_conn_state(self, api_key):
            return FakeDaemonState()

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def is_connected(self):
            return True

        def cancel_job_http(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "cancelled": True, "job_id": kwargs["job_id"]}

    fake_connection = FakeConnection()
    monkeypatch.setattr(items_routes, "backend_conn_pool", FakeBackendConnPool())
    monkeypatch.setattr(
        items_routes,
        "connection_manager",
        type("FakeConnectionManager", (), {"get_connection": lambda self, key: fake_connection})(),
    )

    item_id = str(item.id)
    agent_session_manager.remove_session(item_id)
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")
    session.mark_terminal_job_started(
        RUN_JOB_TOOL_NAME,
        {"item_id": item_id, "command": "apt-get install -y temurin-17-jdk"},
    )
    try:
        response = client.post(
            f"{settings.API_V1_STR}/items/{item.id}/jobs/job-9/cancel",
            headers=superuser_token_headers,
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert response.status_code == 200
    assert fake_connection.calls == [{"item_uuid": item_id, "job_id": "job-9"}]
    assert session.has_running_terminal_job() is False


def test_terminal_token_uses_public_daemon_endpoint(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import items as items_routes

    item = create_random_item(db)
    item.socket_host = "daemon"
    item.socket_port = 9000
    item.api_key = "daemon-key"
    db.add(item)
    db.commit()
    db.refresh(item)

    class FakeSocketPool:
        def get_item_token(self, item_id: str):
            assert item_id == str(item.id)
            return ("daemon:9000:daemon-key", "daemon-token")

    class FakeDaemonState:
        def is_connected(self):
            return True

    class FakeBackendConnPool:
        def get_daemon_main_conn_state(self, api_key: str):
            assert api_key == "daemon-key"
            return FakeDaemonState()

    monkeypatch.setattr(items_routes, "socket_pool_facade", FakeSocketPool())
    monkeypatch.setattr(items_routes, "backend_conn_pool", FakeBackendConnPool())
    monkeypatch.setattr(items_routes.settings, "DAEMON_HOST_PORT", 39999)
    monkeypatch.setattr(items_routes.settings, "DAEMON_PUBLIC_URL", None)
    monkeypatch.setattr(items_routes.settings, "DAEMON_PUBLIC_HOST", None)
    monkeypatch.setattr(items_routes.settings, "DAEMON_PUBLIC_PORT", None)
    monkeypatch.setattr(items_routes.settings, "DAEMON_PUBLIC_WS_SCHEME", "ws")

    response = client.get(
        f"{settings.API_V1_STR}/items/{item.id}/terminal-token",
        headers={**superuser_token_headers, "host": "203.135.104.22:28888"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["ws_url"] == "ws://203.135.104.22:39999"


def test_terminal_token_public_url_override(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import items as items_routes

    item = create_random_item(db)
    item.socket_host = "daemon"
    item.socket_port = 9000
    item.api_key = "daemon-key"
    db.add(item)
    db.commit()
    db.refresh(item)

    class FakeSocketPool:
        def get_item_token(self, item_id: str):
            return ("daemon:9000:daemon-key", "daemon-token")

    class FakeDaemonState:
        def is_connected(self):
            return True

    class FakeBackendConnPool:
        def get_daemon_main_conn_state(self, api_key: str):
            return FakeDaemonState()

    monkeypatch.setattr(items_routes, "socket_pool_facade", FakeSocketPool())
    monkeypatch.setattr(items_routes, "backend_conn_pool", FakeBackendConnPool())
    monkeypatch.setattr(items_routes.settings, "DAEMON_PUBLIC_URL", "https://terminal.example.com")

    response = client.get(
        f"{settings.API_V1_STR}/items/{item.id}/terminal-token",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["ws_url"] == "wss://terminal.example.com"

def test_read_items(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    create_random_item(db)
    create_random_item(db)
    response = client.get(
        f"{settings.API_V1_STR}/items/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert len(content["data"]) >= 2


def test_update_item(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    data = {"title": "Updated title", "description": "Updated description",
            "status": "running", "socket_port": 9001,
            "api_key": "updated-api-key",
            "command": "test command",
            "working_directory": "/path/to/workdir"}
    response = client.put(
        f"{settings.API_V1_STR}/items/{item.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["title"] == data["title"]
    assert content["description"] == data["description"]
    assert content["id"] == str(item.id)
    assert content["owner_id"] == str(item.owner_id)
    # 测试更新新添加的字段
    assert content["status"] == data["status"]
    assert content["socket_port"] == data["socket_port"]
    assert content["api_key"] == data["api_key"]
    assert content["command"] == data["command"]
    assert content["working_directory"] == data["working_directory"]


def test_update_item_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"title": "Updated title", "description": "Updated description"}
    response = client.put(
        f"{settings.API_V1_STR}/items/{uuid.uuid4()}",
        headers=superuser_token_headers,
        json=data,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Item not found"


def test_update_item_not_enough_permissions(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    data = {"title": "Updated title", "description": "Updated description"}
    response = client.put(
        f"{settings.API_V1_STR}/items/{item.id}",
        headers=normal_user_token_headers,
        json=data,
    )
    assert response.status_code == 403
    content = response.json()
    assert content["detail"] == "Not enough permissions"


def test_delete_item(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    response = client.delete(
        f"{settings.API_V1_STR}/items/{item.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "Item deleted successfully"


def test_delete_item_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.delete(
        f"{settings.API_V1_STR}/items/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Item not found"


def test_delete_item_not_enough_permissions(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    item = create_random_item(db)
    response = client.delete(
        f"{settings.API_V1_STR}/items/{item.id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    content = response.json()
    assert content["detail"] == "Not enough permissions"
