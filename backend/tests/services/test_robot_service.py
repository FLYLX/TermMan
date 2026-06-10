import asyncio
from datetime import timedelta
from typing import Any

from sqlmodel import Session

from app.models import RobotItem
from app.plugins.robot.contracts import RobotInboundMessage, RobotReplyTarget
from app.plugins.robot.platforms import (
    _event_mentions_bot,
    _event_replies_to_bot,
    _extract_conversation_metadata,
    _extract_event_mentions,
    _extract_sender_key,
    _extract_sender_metadata,
    send_text_with_bot,
)
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
    sender: dict[str, Any] | None = None,
    conversation: dict[str, Any] | None = None,
    mentions: list[dict[str, Any]] | None = None,
    mentioned_bot: bool = False,
    replied_to_bot: bool = False,
) -> RobotInboundMessage:
    metadata: dict[str, Any] = {}
    if target is not None:
        metadata["target"] = target
    if sender is not None:
        metadata["sender"] = sender
    if conversation is not None:
        metadata["conversation"] = conversation
    if mentions is not None:
        metadata["mentions"] = mentions
    if mentioned_bot:
        metadata["mentioned_bot"] = True
    if replied_to_bot:
        metadata["replied_to_bot"] = True

    return RobotInboundMessage(
        sender_key=sender_key,
        text=text,
        reply_target=RobotReplyTarget(
            target_type="universal",
            target_id="g1",
            metadata=metadata,
        ),
    )


def _capture_queued_chat(monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_enqueue_chat_job(job) -> bool:
        captured["job"] = job
        return True

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)
    return captured


class _FakeBot:
    self_id = "10001"


class _FakeOneBotAdapter:
    connections = {"10001": object()}

    def get_name(self) -> str:
        return "OneBot V11"


class _FakeOneBotBot:
    self_id = "10001"

    def __init__(self) -> None:
        self.adapter = _FakeOneBotAdapter()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_api(self, action: str, **kwargs: Any) -> None:
        self.calls.append((action, kwargs))


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
        reply: Any | None = None,
        sender: dict[str, Any] | None = None,
        user_id: str = "",
        message_type: str = "",
        group_id: str = "",
        guild_id: str = "",
        channel_id: str = "",
    ) -> None:
        self._message = message
        self.to_me = to_me
        self.raw_message = raw_message
        self.reply = reply
        self.sender = sender or {}
        self.user_id = user_id
        self.message_type = message_type
        self.group_id = group_id
        self.guild_id = guild_id
        self.channel_id = channel_id

    def get_message(self) -> list[Any]:
        return self._message

    def get_user_id(self) -> str:
        return self.user_id


def test_send_text_with_bot_uses_onebot_group_and_private_actions() -> None:
    bot = _FakeOneBotBot()

    asyncio.run(
        send_text_with_bot(
            bot,
            RobotReplyTarget(target_type="group", target_id="123456"),
            " 群消息 ",
        )
    )
    asyncio.run(
        send_text_with_bot(
            bot,
            RobotReplyTarget(target_type="private", target_id="654321"),
            "私信消息",
        )
    )

    assert bot.calls == [
        (
            "send_group_msg",
            {
                "group_id": 123456,
                "message": "群消息",
            },
        ),
        (
            "send_private_msg",
            {
                "user_id": 654321,
                "message": "私信消息",
            },
        ),
    ]


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


def test_extract_event_mentions_reads_onebot_at_segments() -> None:
    event = _FakeEvent(
        [
            _FakeSegment(
                "at",
                {"qq": "1512220570", "name": "她喜欢我才钓着我"},
            ),
            _FakeSegment("text", {"text": " 这个人是小男娘"}),
        ]
    )

    assert _extract_event_mentions(event) == [
        {
            "id": "1512220570",
            "qq": "1512220570",
            "name": "她喜欢我才钓着我",
        }
    ]


def test_extract_event_mentions_falls_back_to_raw_cq_at() -> None:
    event = _FakeEvent(
        [],
        raw_message="[CQ:at,qq=1512220570,name=她喜欢我才钓着我] 这个人是小男娘",
    )

    assert _extract_event_mentions(event) == [
        {
            "id": "1512220570",
            "qq": "1512220570",
            "name": "她喜欢我才钓着我",
        }
    ]


def test_event_mentions_bot_detects_to_me_flag() -> None:
    event = _FakeEvent([], to_me=True)

    assert _event_mentions_bot(_FakeBot(), event) is True


def test_event_replies_to_bot_detects_reply_sender() -> None:
    event = _FakeEvent([], reply={"sender": {"user_id": "10001"}})

    assert _event_replies_to_bot(_FakeBot(), event) is True


def test_event_replies_to_bot_ignores_other_sender() -> None:
    event = _FakeEvent([_FakeSegment("reply", {"user_id": "10002"})])

    assert _event_replies_to_bot(_FakeBot(), event) is False


def test_extract_sender_metadata_prefers_group_card() -> None:
    event = _FakeEvent(
        [],
        user_id="10002",
        message_type="group",
        sender={
            "user_id": 10002,
            "nickname": "Nick",
            "card": "Alice",
            "role": "admin",
        },
    )

    assert _extract_sender_metadata("onebot_v11", event) == {
        "platform": "onebot_v11",
        "user_id": "10002",
        "display_name": "Alice",
        "nickname": "Nick",
        "card": "Alice",
        "role": "admin",
        "message_type": "group",
    }


def test_agent_message_context_prefix_includes_mentioned_targets() -> None:
    message = _message(
        "这个人是小男娘",
        sender={
            "user_id": "2537134688",
            "display_name": "只有白龙马知道唐三藏动了情",
        },
        conversation={"type": "group", "id": "369040885"},
        mentions=[
            {
                "id": "1512220570",
                "qq": "1512220570",
                "name": "她喜欢我才钓着我",
            }
        ],
    )

    prefix = robot_service._agent_message_context_prefix(
        message,
        trigger_reason="active_chat_window",
    )

    assert "mentions=她喜欢我才钓着我 (1512220570)" in prefix


def test_onebot_conversation_metadata_uses_group_id() -> None:
    event = _FakeEvent(
        [],
        user_id="10002",
        message_type="group",
        group_id="123456",
    )
    target_data = {"id": "universal-target"}

    conversation = _extract_conversation_metadata("onebot_v11", event, target_data)

    assert conversation == {
        "platform": "onebot_v11",
        "type": "group",
        "id": "123456",
        "target_type": "group",
        "target_id": "123456",
        "group_id": "123456",
        "user_id": "10002",
        "message_type": "group",
    }
    assert (
        _extract_sender_key(
            "onebot_v11",
            event,
            target_data,
            conversation_data=conversation,
        )
        == "onebot_v11:group:123456:10002"
    )


def test_onebot_conversation_metadata_uses_private_user_id() -> None:
    event = _FakeEvent(
        [],
        user_id="654321",
        message_type="private",
    )
    target_data = {"id": "universal-target", "private": True}

    conversation = _extract_conversation_metadata("onebot_v11", event, target_data)

    assert conversation == {
        "platform": "onebot_v11",
        "type": "private",
        "id": "654321",
        "target_type": "private",
        "target_id": "654321",
        "user_id": "654321",
        "message_type": "private",
    }
    assert (
        _extract_sender_key(
            "onebot_v11",
            event,
            target_data,
            conversation_data=conversation,
        )
        == "onebot_v11:private:654321"
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(db, robot, _message("hello"))

    assert response.success is True
    assert response.item_id == str(item.id)
    assert response.route_key == "alpha"
    assert captured["job"].message == "hello"
    assert captured["job"].sender_key == "onebot_v11:group:g1:u1"
    assert isinstance(captured["job"].reply_target, RobotReplyTarget)
    assert response.reply_chunks == []


def test_robot_message_passes_sender_prefix_to_agent(
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello",
            target={"id": "g1"},
            sender={
                "user_id": "u1",
                "display_name": "Alice",
            },
        ),
    )

    assert response.success is True
    assert captured["job"].message == (
        "[Robot message; conversation=group:g1; trigger=plain; sender=Alice (u1)]\nhello"
    )
    assert response.reply_chunks == []


def test_private_robot_message_passes_context_stamp_to_agent(
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello",
            sender_key="onebot_v11:private:u1",
            target={"id": "u1", "private": True},
            sender={
                "user_id": "u1",
                "display_name": "Alice",
            },
        ),
    )

    assert response.success is True
    assert captured["job"].message == (
        "[Robot message; conversation=private:u1; trigger=plain; sender=Alice (u1)]\nhello"
    )
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("/term alpha status?"),
    )

    assert response.success is True
    assert response.item_id == str(item.id)
    assert response.route_key == "alpha"
    assert captured["job"].message == "status?"
    assert captured["job"].sender_key == "onebot_v11:group:g1:u1"
    assert isinstance(captured["job"].reply_target, RobotReplyTarget)
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

    def fail_enqueue_chat_job(_job):
        raise AssertionError("group messages should be filtered before chat dispatch")

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fail_enqueue_chat_job)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello group"),
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello private",
            sender_key="onebot_v11:private:u1",
            target={"id": "u1", "private": True},
        ),
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["job"].message == "hello private"
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("/term alpha status?"),
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["job"].message == "status?"
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

    def fail_enqueue_chat_job(_job):
        raise AssertionError("unmentioned group messages should be filtered")

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fail_enqueue_chat_job)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello group"),
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention", mentioned_bot=True),
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["job"].message == "hello mention"
    assert response.reply_chunks == []


def test_reply_message_type_filter_ignores_at_target_by_default_when_only_mention_allowed(
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

    def fail_enqueue_chat_job(_job):
        raise AssertionError("@ target should be filtered unless mention_match_mode is any")

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fail_enqueue_chat_job)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "这个人是小男娘",
            sender={
                "user_id": "2537134688",
                "display_name": "只有白龙马知道唐三藏动了情",
            },
            conversation={"type": "group", "id": "369040885"},
            mentions=[
                {
                    "id": "1512220570",
                    "qq": "1512220570",
                    "name": "她喜欢我才钓着我",
                }
            ],
        ),
    )

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "reply_message_type_disabled"
    assert response.reply_chunks == []


def test_reply_message_type_filter_allows_at_target_when_mention_match_mode_is_any(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "mention_match_mode": "any",
        },
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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "这个人是小男娘",
            sender={
                "user_id": "2537134688",
                "display_name": "只有白龙马知道唐三藏动了情",
            },
            conversation={"type": "group", "id": "369040885"},
            mentions=[
                {
                    "id": "1512220570",
                    "qq": "1512220570",
                    "name": "她喜欢我才钓着我",
                }
            ],
        ),
    )

    assert response.success is True
    assert response.ignored is False
    assert "trigger=mention_any" in captured["job"].message
    assert "mentions=她喜欢我才钓着我 (1512220570)" in captured["job"].message
    assert response.reply_chunks == []


def test_mention_only_keeps_context_active_after_agent_sends_qq_message(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 15,
        },
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

    queued_jobs: list[Any] = []

    def fake_enqueue_chat_job(job) -> bool:
        queued_jobs.append(job)
        return True

    now = robot_service._now()
    current_time = {"value": now}
    monkeypatch.setattr(robot_service, "_now", lambda: current_time["value"])
    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)

    before_activation = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain before", target={"id": "g1"}),
    )
    assert before_activation.ignored is True
    assert before_activation.reason == "reply_message_type_disabled"

    mentioned = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention", target={"id": "g1"}, mentioned_bot=True),
    )
    assert mentioned.ignored is False
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[0].conversation_key,
        robot_message_sent=False,
        reply_target=queued_jobs[0].reply_target,
    )

    no_tool_reply = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain after no tool reply", target={"id": "g1"}),
    )
    assert no_tool_reply.ignored is True
    assert no_tool_reply.reason == "reply_message_type_disabled"

    mentioned_again = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention again", target={"id": "g1"}, mentioned_bot=True),
    )
    assert mentioned_again.ignored is False
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[-1].conversation_key,
        robot_message_sent=True,
        reply_target=queued_jobs[-1].reply_target,
    )

    current_time["value"] = now + timedelta(seconds=14)

    within_window = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain after mention", target={"id": "g1"}),
    )
    assert within_window.ignored is False
    assert [job.message for job in queued_jobs] == [
        "hello mention",
        "hello mention again",
        "plain after mention",
    ]

    current_time["value"] = now + timedelta(seconds=16)

    expired = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain expired", target={"id": "g1"}),
    )
    assert expired.ignored is True
    assert expired.reason == "reply_message_type_disabled"


def test_reply_context_window_is_scoped_to_current_conversation(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 15,
        },
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

    queued_jobs: list[Any] = []

    def fake_enqueue_chat_job(job) -> bool:
        queued_jobs.append(job)
        return True

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)

    activated = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello mention",
            sender_key="onebot_v11:group:g1:u1",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )
    assert activated.ignored is False
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[0].conversation_key,
        robot_message_sent=True,
        reply_target=queued_jobs[0].reply_target,
    )

    other_group = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "plain in another group",
            sender_key="onebot_v11:group:g2:u2",
            target={"id": "g2"},
            sender={"user_id": "u2", "display_name": "Bob"},
        ),
    )
    assert other_group.ignored is True
    assert other_group.reason == "reply_message_type_disabled"

    other_private = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "plain in private",
            sender_key="onebot_v11:private:u2",
            target={"id": "u2", "private": True},
            sender={"user_id": "u2", "display_name": "Bob"},
        ),
    )
    assert other_private.ignored is True
    assert other_private.reason == "reply_message_type_disabled"

    same_group = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "plain in same group",
            sender_key="onebot_v11:group:g1:u3",
            target={"id": "g1"},
            sender={"user_id": "u3", "display_name": "Carol"},
        ),
    )
    assert same_group.ignored is False
    assert [job.message for job in queued_jobs] == [
        "[Robot message; conversation=group:g1; trigger=mention_bot; sender=Alice (u1)]\nhello mention",
        "[Robot message; conversation=group:g1; trigger=active_chat_window; sender=Carol (u3)]\nplain in same group",
    ]


def test_reply_context_uses_onebot_group_id_before_universal_target_id(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 15,
        },
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

    queued_jobs: list[Any] = []

    def fake_enqueue_chat_job(job) -> bool:
        queued_jobs.append(job)
        return True

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)

    mentioned = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello in group one",
            sender_key="onebot_v11:group:g1:u1",
            target={
                "id": "shared-target",
                "message_type": "group",
                "group_id": "g1",
            },
            conversation={
                "platform": "onebot_v11",
                "type": "group",
                "id": "g1",
                "target_type": "group",
                "target_id": "g1",
                "group_id": "g1",
                "user_id": "u1",
                "message_type": "group",
            },
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )
    assert mentioned.ignored is False
    assert queued_jobs[0].conversation_key == "group:g1"
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[0].conversation_key,
        robot_message_sent=True,
        reply_target=queued_jobs[0].reply_target,
    )

    other_group = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "plain in group two",
            sender_key="onebot_v11:group:g2:u2",
            target={
                "id": "shared-target",
                "message_type": "group",
                "group_id": "g2",
            },
            conversation={
                "platform": "onebot_v11",
                "type": "group",
                "id": "g2",
                "target_type": "group",
                "target_id": "g2",
                "group_id": "g2",
                "user_id": "u2",
                "message_type": "group",
            },
            sender={"user_id": "u2", "display_name": "Bob"},
        ),
    )
    assert other_group.ignored is True
    assert other_group.reason == "reply_message_type_disabled"
    assert [job.conversation_key for job in queued_jobs] == ["group:g1"]


def test_reply_to_bot_only_keeps_context_active_after_agent_sends_qq_message(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 15,
        },
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

    queued_jobs: list[Any] = []

    def fake_enqueue_chat_job(job) -> bool:
        queued_jobs.append(job)
        return True

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)

    replied = robot_service.handle_inbound_message(
        db,
        robot,
        _message("reply text", target={"id": "g1"}, replied_to_bot=True),
    )
    assert replied.ignored is False
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[0].conversation_key,
        robot_message_sent=False,
        reply_target=queued_jobs[0].reply_target,
    )

    no_tool_follow_up = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain after reply without tool", target={"id": "g1"}),
    )
    assert no_tool_follow_up.ignored is True
    assert no_tool_follow_up.reason == "reply_message_type_disabled"

    replied_again = robot_service.handle_inbound_message(
        db,
        robot,
        _message("reply text again", target={"id": "g1"}, replied_to_bot=True),
    )
    assert replied_again.ignored is False
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[-1].conversation_key,
        robot_message_sent=True,
        reply_target=queued_jobs[-1].reply_target,
    )

    follow_up = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain after reply", target={"id": "g1"}),
    )
    assert follow_up.ignored is False
    assert [job.message for job in queued_jobs] == [
        "reply text",
        "reply text again",
        "plain after reply",
    ]


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

    captured = _capture_queued_chat(monkeypatch)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("/term alpha status?"),
    )

    assert response.success is True
    assert captured["job"].message == "status?"
    assert response.reply_chunks == []


def test_robot_message_is_ignored_when_backend_queue_is_full(
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

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", lambda _job: False)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello"),
    )

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "dispatch_queue_full"
    assert response.item_id == str(item.id)
    assert response.route_key == "alpha"
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

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("/send alpha ls -la"),
    )

    assert response.success is True
    assert response.item_id == str(item.id)
    assert written == {"item_id": item.id, "command": "ls -la"}
