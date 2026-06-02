import asyncio

from sqlmodel import Session

from app.models import RobotItem
from app.plugins.robot.contracts import RobotInboundMessage
from app.plugins.robot.bridge_client import robot_bridge_client
from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.service import robot_service
from tests.utils.item import create_random_item
from tests.utils.robot import create_random_robot


def test_dispatch_filtered_output_sends_to_registered_audience(
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

    sent_messages: list[tuple[RobotReplyTarget, str]] = []

    def fake_send_message(robot_id: str, target: RobotReplyTarget, text: str):
        assert robot_id == str(robot.id)
        sent_messages.append((target.model_copy(deep=True), text))

    monkeypatch.setattr(robot_bridge_client, "send_message", fake_send_message)

    robot_service._register_audience(  # noqa: SLF001
        robot.id,
        item.id,
        "group:9527:123456",
        RobotReplyTarget(
            target_type="group",
            target_id="group-openid",
            metadata={"msg_id": "msg-1", "msg_seq": 0},
        ),
    )
    robot_service.dispatch_filtered_output(
        str(item.id),
        "line-one\nline-two",
        item_title=item.title,
    )

    assert len(sent_messages) == 1
    target, text = sent_messages[0]
    assert target.target_type == "group"
    assert target.target_id == "group-openid"
    assert target.metadata["msg_seq"] == 1
    assert text == f"[{item.title}]\nline-one\nline-two"


def _message(text: str) -> RobotInboundMessage:
    return RobotInboundMessage(
        sender_key="onebot_v11:group:g1:u1",
        text=text,
        reply_target=RobotReplyTarget(
            target_type="universal",
            target_id="g1",
            metadata={},
        ),
    )


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
    assert response.reply_chunks == ["agent response"]


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
    assert response.reply_chunks == ["agent response"]


def test_term_response_is_chunked_by_max_message_length(
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
    assert len(response.reply_chunks) == 3
    assert all(len(chunk) <= 1000 for chunk in response.reply_chunks)


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
