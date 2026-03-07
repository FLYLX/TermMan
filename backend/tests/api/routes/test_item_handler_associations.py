import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import ItemHandlerItem, ItemHandlerUser
from tests.utils.item import create_random_item
from tests.utils.item_handler import create_random_item_handler
from tests.utils.user import create_random_user


# Test ItemHandlerItem associations
def test_add_item_to_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    item = create_random_item(db)
    
    # Test the endpoint
    response = client.post(
        f"{settings.API_V1_STR}/item-handler-associations/items",
        headers=superuser_token_headers,
        json={"item_handler_id": str(item_handler.id), "item_id": str(item.id)},
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "Item added to item handler successfully"
    
    # Verify the association was created
    association = db.exec(
        select(ItemHandlerItem)
        .where(ItemHandlerItem.item_handler_id == item_handler.id)
        .where(ItemHandlerItem.item_id == item.id)
    ).first()
    assert association is not None


def test_add_item_to_handler_duplicate(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    item = create_random_item(db)
    
    # Create the association first
    association = ItemHandlerItem(item_handler_id=item_handler.id, item_id=item.id)
    db.add(association)
    db.commit()
    
    # Test adding again
    response = client.post(
        f"{settings.API_V1_STR}/item-handler-associations/items",
        headers=superuser_token_headers,
        json={"item_handler_id": str(item_handler.id), "item_id": str(item.id)},
    )
    
    assert response.status_code == 400
    content = response.json()
    assert content["detail"] == "Item is already associated with this item handler"


def test_add_item_to_handler_not_found(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Test with non-existent item handler
    item = create_random_item(db)
    response = client.post(
        f"{settings.API_V1_STR}/item-handler-associations/items",
        headers=superuser_token_headers,
        json={"item_handler_id": str(uuid.uuid4()), "item_id": str(item.id)},
    )
    
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Item handler not found"
    
    # Test with non-existent item
    item_handler = create_random_item_handler(db)
    response = client.post(
        f"{settings.API_V1_STR}/item-handler-associations/items",
        headers=superuser_token_headers,
        json={"item_handler_id": str(item_handler.id), "item_id": str(uuid.uuid4())},
    )
    
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Item not found"


def test_remove_item_from_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    item = create_random_item(db)
    
    # Create the association
    association = ItemHandlerItem(item_handler_id=item_handler.id, item_id=item.id)
    db.add(association)
    db.commit()
    
    # Test the endpoint
    response = client.delete(
        f"{settings.API_V1_STR}/item-handler-associations/items/{str(item_handler.id)}/{str(item.id)}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "Item removed from item handler successfully"
    
    # Verify the association was removed
    association = db.exec(
        select(ItemHandlerItem)
        .where(ItemHandlerItem.item_handler_id == item_handler.id)
        .where(ItemHandlerItem.item_id == item.id)
    ).first()
    assert association is None


def test_remove_item_from_handler_not_found(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Test with non-existent association
    response = client.delete(
        f"{settings.API_V1_STR}/item-handler-associations/items/{str(uuid.uuid4())}/{str(uuid.uuid4())}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 404
    content = response.json()
    assert content["detail"] == "Association not found"


def test_get_items_for_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    item1 = create_random_item(db)
    item2 = create_random_item(db)
    
    # Create associations
    association1 = ItemHandlerItem(item_handler_id=item_handler.id, item_id=item1.id)
    association2 = ItemHandlerItem(item_handler_id=item_handler.id, item_id=item2.id)
    db.add(association1)
    db.add(association2)
    db.commit()
    
    # Test the endpoint
    response = client.get(
        f"{settings.API_V1_STR}/item-handler-associations/items/{str(item_handler.id)}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert len(content) == 2
    assert any(item["id"] == str(item1.id) for item in content)
    assert any(item["id"] == str(item2.id) for item in content)


def test_get_handlers_for_item(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item = create_random_item(db)
    handler1 = create_random_item_handler(db)
    handler2 = create_random_item_handler(db)
    
    # Create associations
    association1 = ItemHandlerItem(item_handler_id=handler1.id, item_id=item.id)
    association2 = ItemHandlerItem(item_handler_id=handler2.id, item_id=item.id)
    db.add(association1)
    db.add(association2)
    db.commit()
    
    # Test the endpoint
    response = client.get(
        f"{settings.API_V1_STR}/item-handler-associations/item-handlers/{str(item.id)}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert len(content) == 2
    assert any(handler["id"] == str(handler1.id) for handler in content)
    assert any(handler["id"] == str(handler2.id) for handler in content)


# Test ItemHandlerUser associations
def test_add_user_to_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    user = create_random_user(db)
    
    # Test the endpoint
    response = client.post(
        f"{settings.API_V1_STR}/item-handler-associations/users",
        headers=superuser_token_headers,
        json={"item_handler_id": str(item_handler.id), "user_id": str(user.id)},
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "User added to item handler successfully"
    
    # Verify the association was created
    association = db.exec(
        select(ItemHandlerUser)
        .where(ItemHandlerUser.item_handler_id == item_handler.id)
        .where(ItemHandlerUser.user_id == user.id)
    ).first()
    assert association is not None


def test_add_user_to_handler_duplicate(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    user = create_random_user(db)
    
    # Create the association first
    association = ItemHandlerUser(item_handler_id=item_handler.id, user_id=user.id)
    db.add(association)
    db.commit()
    
    # Test adding again
    response = client.post(
        f"{settings.API_V1_STR}/item-handler-associations/users",
        headers=superuser_token_headers,
        json={"item_handler_id": str(item_handler.id), "user_id": str(user.id)},
    )
    
    assert response.status_code == 400
    content = response.json()
    assert content["detail"] == "User is already associated with this item handler"


def test_remove_user_from_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    user = create_random_user(db)
    
    # Create the association
    association = ItemHandlerUser(item_handler_id=item_handler.id, user_id=user.id)
    db.add(association)
    db.commit()
    
    # Test the endpoint
    response = client.delete(
        f"{settings.API_V1_STR}/item-handler-associations/users/{str(item_handler.id)}/{str(user.id)}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["message"] == "User removed from item handler successfully"
    
    # Verify the association was removed
    association = db.exec(
        select(ItemHandlerUser)
        .where(ItemHandlerUser.item_handler_id == item_handler.id)
        .where(ItemHandlerUser.user_id == user.id)
    ).first()
    assert association is None


def test_get_users_for_handler(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    item_handler = create_random_item_handler(db)
    user1 = create_random_user(db)
    user2 = create_random_user(db)
    
    # Create associations
    association1 = ItemHandlerUser(item_handler_id=item_handler.id, user_id=user1.id)
    association2 = ItemHandlerUser(item_handler_id=item_handler.id, user_id=user2.id)
    db.add(association1)
    db.add(association2)
    db.commit()
    
    # Test the endpoint
    response = client.get(
        f"{settings.API_V1_STR}/item-handler-associations/users/{str(item_handler.id)}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert len(content) == 2
    assert any(user["id"] == str(user1.id) for user in content)
    assert any(user["id"] == str(user2.id) for user in content)


def test_get_handlers_for_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    user = create_random_user(db)
    handler1 = create_random_item_handler(db)
    handler2 = create_random_item_handler(db)
    
    # Create associations
    association1 = ItemHandlerUser(item_handler_id=handler1.id, user_id=user.id)
    association2 = ItemHandlerUser(item_handler_id=handler2.id, user_id=user.id)
    db.add(association1)
    db.add(association2)
    db.commit()
    
    # Test the endpoint
    response = client.get(
        f"{settings.API_V1_STR}/item-handler-associations/user-handlers/{str(user.id)}",
        headers=superuser_token_headers,
    )
    
    assert response.status_code == 200
    content = response.json()
    assert len(content) == 2
    assert any(handler["id"] == str(handler1.id) for handler in content)
    assert any(handler["id"] == str(handler2.id) for handler in content)


# Test permission checks
def test_add_item_to_handler_permission_denied(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    # Create test data
    # User1 creates an item handler
    item_handler = create_random_item_handler(db)
    # User2 creates an item
    user2 = create_random_user(db)
    
    # We can't directly pass owner_id to create_random_item, so we need to modify the function
    # For now, let's just test that normal users can't modify item handlers they don't own
    response = client.post(
        f"{settings.API_V1_STR}/item-handler-associations/items",
        headers=normal_user_token_headers,
        json={"item_handler_id": str(item_handler.id), "item_id": str(create_random_item(db).id)},
    )
    
    assert response.status_code == 403
    content = response.json()
    assert content["detail"] == "Not enough permissions to modify this item handler"
