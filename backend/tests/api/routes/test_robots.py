from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.plugins.robot.bridge_client import robot_bridge_client
from app.plugins.robot.service import robot_service
from tests.utils.item import create_random_item


def test_list_robot_platforms(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/robots/platforms",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    platforms = response.json()
    platform_ids = {platform["id"] for platform in platforms}
    assert platform_ids == {"onebot_v11"}
    assert len(platforms) == 1


def test_create_robot_normalizes_legacy_platform_alias(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(robot_bridge_client, "notify_reload", lambda: None)

    response = client.post(
        f"{settings.API_V1_STR}/robots/",
        headers=superuser_token_headers,
        json={
            "name": "QQ Robot",
            "platform": "qq",
            "provider": "nonebot2",
            "is_enabled": True,
            "config": {
                "credentials": {
                    "self_id": "1024",
                    "ws_url": "ws://napcat.test:3001",
                },
                "options": {},
            },
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["name"] == "QQ Robot"
    assert content["platform"] == "onebot_v11"
    assert content["protocol"] == "onebot_v11"
    assert content["provider"] == "nonebot2"
    assert content["app_id"] is None
    assert content["app_secret"] is None
    assert content["bot_token"] is None
    assert content["use_websocket"] is False
    assert content["config"]["credentials"]["self_id"] == "1024"


def test_create_unsupported_robot_platform_is_rejected(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(robot_bridge_client, "notify_reload", lambda: None)

    response = client.post(
        f"{settings.API_V1_STR}/robots/",
        headers=superuser_token_headers,
        json={
            "name": "Telegram Robot",
            "platform": "telegram",
            "provider": "nonebot2",
            "is_enabled": True,
            "config": {
                "credentials": {
                    "bot_token": "123456:test-token",
                },
                "options": {},
            },
        },
    )

    assert response.status_code == 400
    assert "Only NapCat OneBot V11 is currently supported" in response.json()["detail"]


def test_bind_item_to_robot(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(robot_bridge_client, "notify_reload", lambda: None)
    item = create_random_item(db)
    robot_response = client.post(
        f"{settings.API_V1_STR}/robots/",
        headers=superuser_token_headers,
        json={
            "name": "binding-robot",
            "platform": "onebot_v11",
            "provider": "nonebot2",
            "config": {
                "credentials": {
                    "self_id": "2048",
                    "ws_url": "ws://napcat.test:3001",
                },
                "options": {},
            },
        },
    )
    robot_id = robot_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/robots/{robot_id}/items",
        headers=superuser_token_headers,
        json={
            "item_id": str(item.id),
            "allow_chat": True,
            "receive_filtered_output": True,
            "chat_alias": "alpha-room",
            "is_default_target": True,
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["item_id"] == str(item.id)
    assert content["allow_chat"] is True
    assert content["receive_filtered_output"] is True
    assert content["chat_alias"] == "alpha-room"
    assert content["route_key"] == "alpha-room"
    assert content["is_default_target"] is True


def test_dispatch_robot_message_routes_to_item_agent(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(robot_bridge_client, "notify_reload", lambda: None)
    item = create_random_item(db)
    robot_response = client.post(
        f"{settings.API_V1_STR}/robots/",
        headers=superuser_token_headers,
        json={
            "name": "dispatch-robot",
            "platform": "onebot_v11",
            "provider": "nonebot2",
            "config": {
                "credentials": {
                    "self_id": "4096",
                    "ws_url": "ws://napcat.test:3001",
                },
                "options": {},
            },
        },
    )
    robot_id = robot_response.json()["id"]

    bind_response = client.post(
        f"{settings.API_V1_STR}/robots/{robot_id}/items",
        headers=superuser_token_headers,
        json={
            "item_id": str(item.id),
            "allow_chat": True,
            "chat_alias": "alpha",
            "receive_filtered_output": True,
            "is_default_target": True,
        },
    )
    assert bind_response.status_code == 200

    expected_item_id = item.id

    async def fake_chat_with_item(*, session, robot, item, message):
        del session, robot
        assert message == "status?"
        assert item.id == expected_item_id
        return "agent-ok"

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    response = client.post(
        f"{settings.API_V1_STR}/robots/{robot_id}/dispatch",
        headers={"X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY},
        json={
            "sender_key": "group_group-1_member-1",
            "text": "/term alpha status?",
            "reply_target": {
                "target_type": "group",
                "target_id": "group-openid",
                "metadata": {
                    "msg_id": "msg-1",
                    "msg_seq": 0,
                },
            },
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["success"] is True
    assert content["ignored"] is False
    assert content["item_id"] == str(item.id)
    assert content["route_key"] == "alpha"
    assert content["reply_chunks"] == ["agent-ok"]


def test_dispatch_robot_message_rejects_invalid_bridge_token(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(robot_bridge_client, "notify_reload", lambda: None)
    robot_response = client.post(
        f"{settings.API_V1_STR}/robots/",
        headers=superuser_token_headers,
        json={
            "name": "auth-robot",
            "platform": "onebot_v11",
            "provider": "nonebot2",
            "config": {
                "credentials": {
                    "self_id": "8192",
                    "ws_url": "ws://napcat.test:3001",
                },
                "options": {},
            },
        },
    )
    robot_id = robot_response.json()["id"]

    response = client.post(
        f"{settings.API_V1_STR}/robots/{robot_id}/dispatch",
        headers={"X-TermMan-Bridge-Token": "wrong-token"},
        json={
            "sender_key": "friend_openid",
            "text": "ping",
            "reply_target": {
                "target_type": "c2c",
                "target_id": "user-openid",
                "metadata": {
                    "msg_id": "msg-2",
                    "msg_seq": 0,
                },
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid robot bridge token"
