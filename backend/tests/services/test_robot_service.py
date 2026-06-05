import asyncio
from typing import Any

from sqlmodel import Session

from app.models import RobotItem
from app.plugins.robot.contracts import RobotInboundMessage, RobotReplyTarget
from app.plugins.robot.platforms import _event_mentions_bot
from app.plugins.robot.service import robot_service
from tests.utils.item import create_random_item
from tests.utils.robot import create_random_robot


def test_dispatch_filtered_output_does_not_send_to_robot(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)

    binding = RobotItem(
        robot_id=robot.id,
        item_id=item.id,
        allow_chat=True,
        receive_filtered_output=True,
        chat_alias="alpha",
        is_default_target=True,
    )
    db.add(binding)
    db.commit()

    def fail_send():
        raise AssertionError("terminal output should not be sent to robot")

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fail_send,
    )
    robot_service.dispatch_filtered_output(
        str(item.id),
        "line-one\nline-two",
        item_title=item.title,
    )


def _message(
    text: str,
    *,
    sender_key: str = "onebot_v11:group:g1:u1",
    target: dict[str, Any] | None = None,
    mentioned_bot: bool = False,
) -> RobotInboundMessage:
    metadata: dict[str, Any] = {}
    if target is not None:
        metadata["target"] = target
    if mentioned_bot:
        metadata["mentioned_bot"] = True

    return RobotInboundMessage(
        sender_key=sender_key,
        text=text,
        reply_target=RobotReplyTarget(
            target_type="universal",
            target_id="g1",
            metadata=metadata,
        ),
    )


class _FakeBot:
    self_id = "10001"


class _FakeSegment:
    def __init__(self, segment_type: str, data: dict[str, Any]) -> None:
        self.type = segment_type
        self.data = data


class _FakeEvent:
    def __init__(
        self,
        message: list[Any],
        *,
        to_me: bool = False,
        raw_message: str = "",
    ) -> None:
        self._message = message
        self.to_me = to_me
        self.raw_message = raw_message

    def get_message(self) -> list[Any]:
        return self._message


def test_event_mentions_bot_detects_onebot_at_segment() -> None:
    event = _FakeEvent(
        [
            _FakeSegment("at", {"qq": "10001"}),
            _FakeSegment("text", {"text": " hello"}),
        ]
    )

    assert _event_mentions_bot(_FakeBot(), event) is True


def test_event_mentions_bot_ignores_other_at_segment() -> None:
    event = _FakeEvent([_FakeSegment("at", {"qq": "10002"})])

    assert _event_mentions_bot(_FakeBot(), event) is False


def test_event_mentions_bot_detects_to_me_flag() -> None:
    event = _FakeEvent([], to_me=True)

    assert _event_mentions_bot(_FakeBot(), event) is True


def test_plain_robot_message_routes_to_default_item_agent(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=True,
        )
    )
    db.commit()

    captured: dict[str, object] = {}

    async def fake_chat_with_item(**kwargs):
        captured.update(kwargs)
        return "agent response"

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(db, robot, _message("hello"))
    )

    assert response.success is True
    assert response.item_id == str(item.id)
    assert response.route_key == "alpha"
    assert captured["message"] == "hello"
    assert captured["sender_key"] == "onebot_v11:group:g1:u1"
    assert isinstance(captured["reply_target"], RobotReplyTarget)
    assert response.reply_chunks == []


def test_term_command_routes_to_named_item_agent(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=False,
        )
    )
    db.commit()

    captured: dict[str, object] = {}

    async def fake_chat_with_item(**kwargs):
        captured.update(kwargs)
        return "agent response"

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(
            db,
            robot,
            _message("/term alpha status?"),
        )
    )

    assert response.success is True
    assert response.item_id == str(item.id)
    assert response.route_key == "alpha"
    assert captured["message"] == "status?"
    assert captured["sender_key"] == "onebot_v11:group:g1:u1"
    assert isinstance(captured["reply_target"], RobotReplyTarget)
    assert response.reply_chunks == []


def test_reply_message_type_filter_ignores_unselected_group_message(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {"reply_message_types": ["private"]},
    }
    db.add(robot)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=True,
        )
    )
    db.commit()

    async def fail_chat_with_item(**_kwargs):
        raise AssertionError("group messages should be filtered before chat dispatch")

    monkeypatch.setattr(robot_service, "_chat_with_item", fail_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(db, robot, _message("hello group"))
    )

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "reply_message_type_disabled"
    assert response.reply_chunks == []


def test_reply_message_type_filter_allows_configured_private_message(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {"reply_message_types": ["private"]},
    }
    db.add(robot)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=True,
        )
    )
    db.commit()

    captured: dict[str, object] = {}

    async def fake_chat_with_item(**kwargs):
        captured.update(kwargs)
        return "private response"

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(
            db,
            robot,
            _message(
                "hello private",
                sender_key="onebot_v11:private:u1",
                target={"id": "u1", "private": True},
            ),
        )
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["message"] == "hello private"
    assert response.reply_chunks == []


def test_reply_message_type_filter_allows_command_when_scope_is_disabled(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {"reply_message_types": ["command"]},
    }
    db.add(robot)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=False,
        )
    )
    db.commit()

    captured: dict[str, object] = {}

    async def fake_chat_with_item(**kwargs):
        captured.update(kwargs)
        return "command response"

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(
            db,
            robot,
            _message("/term alpha status?"),
        )
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["message"] == "status?"
    assert response.reply_chunks == []


def test_reply_message_type_filter_ignores_unmentioned_when_only_mention_allowed(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {"reply_message_types": ["mention"]},
    }
    db.add(robot)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=True,
        )
    )
    db.commit()

    async def fail_chat_with_item(**_kwargs):
        raise AssertionError("unmentioned group messages should be filtered")

    monkeypatch.setattr(robot_service, "_chat_with_item", fail_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(db, robot, _message("hello group"))
    )

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "reply_message_type_disabled"
    assert response.reply_chunks == []


def test_reply_message_type_filter_allows_mention_when_group_is_disabled(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {"reply_message_types": ["mention"]},
    }
    db.add(robot)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=True,
        )
    )
    db.commit()

    captured: dict[str, object] = {}

    async def fake_chat_with_item(**kwargs):
        captured.update(kwargs)
        return "mention response"

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(
            db,
            robot,
            _message("hello mention", mentioned_bot=True),
        )
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["message"] == "hello mention"
    assert response.reply_chunks == []


def test_term_agent_response_is_not_auto_chunked_for_bridge(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {"max_message_length": 1000},
    }
    db.add(robot)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=False,
        )
    )
    db.commit()

    async def fake_chat_with_item(**kwargs):
        assert kwargs["message"] == "status?"
        return "x" * 3000

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    response = asyncio.run(
        robot_service.handle_inbound_message(
            db,
            robot,
            _message("/term alpha status?"),
        )
    )

    assert response.success is True
    assert response.reply_chunks == []


def test_send_command_writes_directly_to_terminal(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=False,
        )
    )
    db.commit()

    written: dict[str, object] = {}

    def fake_write(item_id, command):
        written["item_id"] = item_id
        written["command"] = command
        return True

    monkeypatch.setattr(robot_service, "_write_to_item_terminal", fake_write)

    response = asyncio.run(
        robot_service.handle_inbound_message(
            db,
            robot,
            _message("/send alpha ls -la"),
        )
    )

    assert response.success is True
    assert response.item_id == str(item.id)
    assert written == {"item_id": item.id, "command": "ls -la"}
