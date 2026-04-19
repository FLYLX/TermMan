from sqlmodel import Session

from app.models import RobotItem
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
