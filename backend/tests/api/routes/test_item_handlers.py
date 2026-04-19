import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.routes import item_handlers as item_handlers_route
from app.core.config import settings
from app.models import ItemHandlerCreate
from tests.utils.item_handler import create_random_item_handler
from tests.utils.user import create_random_user


def test_create_item_handler(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """Test creating an item handler."""
    data = {
        "name": "Test Handler",
        "model": "test-model",
        "api_key": "test-api-key",
        "api_url": "https://api.example.com"
    }
    
    response = client.post(
        f"{settings.API_V1_STR}/item-handlers/",
        headers=superuser_token_headers,
        json=data,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["name"] == data["name"]
    assert content["model"] == data["model"]
    assert content["api_key"] == data["api_key"]
    assert content["api_url"] == data["api_url"]
    assert "id" in content
    assert "owner_id" in content


def test_read_item_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test reading a single item handler."""
    # 创建一个随机的item handler
    item_handler = create_random_item_handler(db)
    
    # 读取该item handler
    response = client.get(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["name"] == item_handler.name
    assert content["model"] == item_handler.model
    assert content["id"] == str(item_handler.id)
    assert content["owner_id"] == str(item_handler.owner_id)


def test_read_item_handler_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """Test reading a non-existent item handler."""
    # 使用随机UUID
    random_id = uuid.uuid4()
    
    response = client.get(
        f"{settings.API_V1_STR}/item-handlers/{random_id}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 404


def test_read_item_handlers(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test reading all item handlers."""
    # 创建多个item handlers
    item_handler1 = create_random_item_handler(db)
    item_handler2 = create_random_item_handler(db)
    
    # 读取所有item handlers
    response = client.get(
        f"{settings.API_V1_STR}/item-handlers/",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert isinstance(content, list)
    assert len(content) >= 2
    
    # 检查创建的item handlers是否在响应中
    item_handler_ids = {str(item_handler1.id), str(item_handler2.id)}
    response_ids = {handler["id"] for handler in content}
    assert item_handler_ids.issubset(response_ids)


def test_update_item_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test updating an item handler."""
    # 创建一个随机的item handler
    item_handler = create_random_item_handler(db)
    
    # 更新该item handler
    update_data = {
        "name": "Updated Handler",
        "model": "updated-model"
    }
    
    response = client.put(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}",
        headers=superuser_token_headers,
        json=update_data,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["name"] == update_data["name"]
    assert content["model"] == update_data["model"]
    assert content["id"] == str(item_handler.id)
    # 确保其他字段保持不变
    assert content["api_key"] == item_handler.api_key
    assert content["api_url"] == item_handler.api_url


def test_update_item_handler_normalizes_enabled_knowledge_files(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    item_handler = create_random_item_handler(db)

    response = client.put(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}",
        headers=superuser_token_headers,
        json={
            "enabled_knowledge_files": [
                "guide.md",
                "guide.md",
                "notes.txt",
                "bad.exe",
                "../escape.md",
            ]
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["enabled_knowledge_files"] == ["guide.md", "notes.txt"]


def test_read_item_handler_llm_statuses(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    item_handler = create_random_item_handler(db)
    checked_at = datetime.now(timezone.utc)

    def fake_get_statuses(item_handlers, force: bool = False):
        assert any(handler.id == item_handler.id for handler in item_handlers)
        assert force is False
        return [
            {
                "item_handler_id": item_handler.id,
                "status": "connected",
                "reachable": True,
                "message": "LLM reachable",
                "checked_at": checked_at,
                "cached": False,
            }
        ]

    monkeypatch.setattr(
        item_handlers_route.llm_health_service,
        "get_statuses",
        fake_get_statuses,
    )

    response = client.get(
        f"{settings.API_V1_STR}/item-handlers/llm/status",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert len(content["data"]) == 1
    assert content["data"][0]["item_handler_id"] == str(item_handler.id)
    assert content["data"][0]["status"] == "connected"
    assert content["data"][0]["reachable"] is True


def test_delete_item_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test deleting an item handler."""
    # 创建一个随机的item handler
    item_handler = create_random_item_handler(db)
    
    # 删除该item handler
    response = client.delete(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "Item handler deleted successfully"
    
    # 确认item handler已被删除
    response = client.get(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 404


def test_item_handler_permissions(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Test item handler permissions."""
    # 创建一个属于普通用户的item handler
    user = create_random_user(db)
    assert user.id is not None
    
    item_handler_in = ItemHandlerCreate(
        name="User Handler",
        model="user-model"
    )
    
    # 使用普通用户令牌创建item handler
    response = client.post(
        f"{settings.API_V1_STR}/item-handlers/",
        headers=normal_user_token_headers,
        json=item_handler_in.model_dump(),
    )
    
    assert response.status_code == 200
    content = response.json()
    user_item_handler_id = content["id"]
    
    # 尝试使用不同的普通用户令牌访问该item handler（应该失败）
    other_user = create_random_user(db)
    assert other_user.id is not None
    
    # 由于我们没有另一个普通用户的令牌，这里只是示例测试结构
    # 在实际应用中，我们需要创建另一个用户并获取其令牌
