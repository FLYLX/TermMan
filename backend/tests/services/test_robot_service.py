import asyncio
from datetime import timedelta
from typing import Any

from sqlmodel import Session

from app.models import RobotItem
from app.plugins.robot.contracts import RobotInboundMessage, RobotReplyTarget
from app.plugins.robot.conversation_memory import robot_conversation_memory
from app.plugins.robot.platforms import (
    _event_mentions_bot,
    _event_replies_to_bot,
    _extract_conversation_metadata,
    _extract_event_mentions,
    _extract_sender_key,
    _extract_sender_metadata,
    build_inbound_message,
    send_text_with_bot,
)
from app.plugins.robot.service import robot_service
from app.services.agent.chat_runtime import ChatResponseResult
from app.services.agent.memory.vector_store import vector_store
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


def test_enqueue_background_job_result_targets_original_conversation(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    captured = _capture_queued_chat(monkeypatch)
    target = RobotReplyTarget(
        target_type="private",
        target_id="2537134688",
        metadata={"mentioned_bot": True},
    )

    queued = robot_service.enqueue_background_job_result(
        robot_id=robot.id,
        item_id=item.id,
        sender_key="2537134688",
        reply_target=target,
        conversation_key="private:2537134688",
        conversation_generation=12,
        message="[Background terminal job result]\nTemurin installed",
    )

    assert queued is True
    job = captured["job"]
    assert job.robot_id == robot.id
    assert job.item_id == item.id
    assert job.sender_key == "2537134688"
    assert job.reply_target.target_id == "2537134688"
    assert job.conversation_key == "private:2537134688"
    assert job.conversation_generation == 12
    assert job.direct_reply_trigger is True
    assert job.reply_requires_awake is False
    assert "Temurin installed" in job.message


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
    bot_self_ids: list[str] | None = None,
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
    if bot_self_ids is not None:
        metadata["bot_self_ids"] = bot_self_ids

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

    def get_plaintext(self) -> str:
        texts: list[str] = []
        for segment in self._message:
            if getattr(segment, "type", "") == "text":
                texts.append(str(getattr(segment, "data", {}).get("text") or ""))
        return "".join(texts)


class _FakeAlconnaTarget:
    id = "123456"
    source = None

    def dump(self) -> dict[str, Any]:
        return {"id": self.id}


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


def test_send_text_with_bot_converts_onebot_group_cq_at_to_segment() -> None:
    bot = _FakeOneBotBot()

    asyncio.run(
        send_text_with_bot(
            bot,
            RobotReplyTarget(target_type="group", target_id="123456"),
            "[CQ:at,qq=3385417251] hello",
        )
    )

    assert bot.calls == [
        (
            "send_group_msg",
            {
                "group_id": 123456,
                "message": [
                    {"type": "at", "data": {"qq": "3385417251"}},
                    {"type": "text", "data": {"text": " hello"}},
                ],
            },
        )
    ]


def test_send_text_with_bot_converts_onebot_metadata_group_cq_at_to_segment() -> None:
    bot = _FakeOneBotBot()

    asyncio.run(
        send_text_with_bot(
            bot,
            RobotReplyTarget(
                target_type="universal",
                target_id="universal-target",
                metadata={
                    "target": {
                        "id": "universal-target",
                        "message_type": "group",
                        "group_id": "123456",
                    }
                },
            ),
            "reply [CQ:at,qq=3385417251]",
        )
    )

    assert bot.calls == [
        (
            "send_group_msg",
            {
                "group_id": 123456,
                "message": [
                    {"type": "text", "data": {"text": "reply "}},
                    {"type": "at", "data": {"qq": "3385417251"}},
                ],
            },
        )
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


def test_event_mentions_bot_ignores_other_at_even_when_to_me_flag_is_set() -> None:
    event = _FakeEvent([_FakeSegment("at", {"qq": "10002"})], to_me=True)

    assert _event_mentions_bot(_FakeBot(), event) is False


def test_event_mentions_bot_ignores_group_to_me_without_self_at() -> None:
    event = _FakeEvent(
        [_FakeSegment("text", {"text": "hello"})],
        to_me=True,
        message_type="group",
        raw_message="[CQ:at,qq=10002] hello",
    )

    assert _event_mentions_bot(_FakeBot(), event) is False


def test_service_direct_trigger_requires_bot_self_id_mention() -> None:
    message = _message(
        "[CQ:at,qq=20002] hello",
        sender_key="onebot_v11:group:g1:u1",
        target={"id": "g1", "message_type": "group", "group_id": "g1"},
        mentioned_bot=True,
        bot_self_ids=["10001"],
        mentions=[{"id": "20002", "qq": "20002"}],
    )

    assert robot_service._message_directly_addresses_bot(message) is False


def test_service_direct_trigger_accepts_bot_self_id_mention() -> None:
    message = _message(
        "[CQ:at,qq=10001] hello",
        sender_key="onebot_v11:group:g1:u1",
        target={"id": "g1", "message_type": "group", "group_id": "g1"},
        mentioned_bot=True,
        bot_self_ids=["10001"],
        mentions=[{"id": "10001", "qq": "10001"}],
    )

    assert robot_service._message_directly_addresses_bot(message) is True

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


def test_build_inbound_message_keeps_empty_bot_mention(monkeypatch) -> None:
    monkeypatch.setattr(
        "nonebot_plugin_alconna.get_message_id",
        lambda event, bot: "message-1",
    )
    monkeypatch.setattr(
        "nonebot_plugin_alconna.get_target",
        lambda event, bot: _FakeAlconnaTarget(),
    )
    event = _FakeEvent(
        [_FakeSegment("at", {"qq": "10001"})],
        user_id="10002",
        message_type="group",
        group_id="123456",
    )

    inbound = build_inbound_message("onebot_v11", _FakeBot(), event)

    assert inbound is not None
    assert inbound.text == "[CQ:at,qq=10001]"
    assert inbound.reply_target.metadata["mentioned_bot"] is True
    assert inbound.reply_target.metadata["bot_self_ids"] == ["10001"]
    assert inbound.reply_target.metadata["message"]["segments"] == [
        {"type": "at", "data": {"qq": "10001"}}
    ]
    assert inbound.reply_target.metadata["conversation"]["id"] == "123456"


def test_build_inbound_message_preserves_onebot_at_in_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "nonebot_plugin_alconna.get_message_id",
        lambda event, bot: "message-1",
    )
    monkeypatch.setattr(
        "nonebot_plugin_alconna.get_target",
        lambda event, bot: _FakeAlconnaTarget(),
    )
    event = _FakeEvent(
        [
            _FakeSegment("at", {"qq": "20002"}),
            _FakeSegment("text", {"text": " hello"}),
        ],
        user_id="10002",
        message_type="group",
        group_id="123456",
    )

    inbound = build_inbound_message("onebot_v11", _FakeBot(), event)

    assert inbound is not None
    assert inbound.text == "[CQ:at,qq=20002] hello"
    assert inbound.reply_target.metadata["mentions"] == [
        {"id": "20002", "qq": "20002"}
    ]
    assert inbound.reply_target.metadata["message"]["plain_text"] == "hello"
    assert inbound.reply_target.metadata["message"]["segments"] == [
        {"type": "at", "data": {"qq": "20002"}},
        {"type": "text", "data": {"text": " hello"}},
    ]


def test_build_inbound_message_drops_empty_non_mention(monkeypatch) -> None:
    monkeypatch.setattr(
        "nonebot_plugin_alconna.get_message_id",
        lambda event, bot: "message-1",
    )
    monkeypatch.setattr(
        "nonebot_plugin_alconna.get_target",
        lambda event, bot: _FakeAlconnaTarget(),
    )
    event = _FakeEvent(
        [],
        user_id="10002",
        message_type="group",
        group_id="123456",
    )

    assert build_inbound_message("onebot_v11", _FakeBot(), event) is None


def test_event_replies_to_bot_detects_reply_sender() -> None:
    event = _FakeEvent([], reply={"sender": {"user_id": "10001"}})

    assert _event_replies_to_bot(_FakeBot(), event) is True


def test_event_replies_to_bot_ignores_reply_event_self_id() -> None:
    event = _FakeEvent([], reply={"self_id": "10001", "message_id": "42"})

    assert _event_replies_to_bot(_FakeBot(), event) is False


def test_event_replies_to_bot_detects_reply_segment_sender_qq() -> None:
    event = _FakeEvent([_FakeSegment("reply", {"qq": "10001"})])

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


def test_agent_message_context_marks_bot_self_mention_for_agent() -> None:
    message = _message(
        "[CQ:at,qq=10001] hello",
        sender={"user_id": "u1", "display_name": "Alice"},
        conversation={"type": "group", "id": "g1"},
        mentions=[{"id": "10001", "qq": "10001", "name": "Bot"}],
        mentioned_bot=True,
        bot_self_ids=["10001"],
    )

    text = robot_service._agent_message_with_context(
        message,
        message.text,
        trigger_reason="mention_bot",
    )

    assert "mentions=Bot (10001) (you)" in text
    assert "[Robot identity; background only]" in text
    assert "- self_id: 10001 (this QQ id is you, the bot)" in text
    assert "- addressed_to_bot: true" in text
    assert "- direct_reason: mention_bot" in text
    assert "- mentioned_self: true" in text
    assert "- replied_to_self: false" in text
    assert "QQ mentions/replies to this self_id are addressing you" in text


def test_robot_reply_context_summary_marks_reply_to_self() -> None:
    from app.plugins.robot.mcp.context import build_robot_reply_context_summary

    message = _message(
        "continue",
        sender={"user_id": "u1", "display_name": "Alice"},
        conversation={"type": "group", "id": "g1"},
        replied_to_bot=True,
        bot_self_ids=["10001"],
    )

    summary = build_robot_reply_context_summary(message.reply_target, message.sender_key)

    assert "- bot_self_id: 10001 (this QQ id is you, the bot)" in summary
    assert "- addressed_to_bot: true" in summary
    assert "- direct_reason: reply_to_bot" in summary
    assert "- mentioned_self: false" in summary
    assert "- replied_to_self: true" in summary
    assert "QQ mentions/replies to this self_id are addressing you" in summary
    assert "reference rule" in summary
    assert "pronouns" in summary


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


def test_plain_group_message_is_ignored_by_default(
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

    def fail_enqueue_chat_job(_job):
        raise AssertionError("plain group chatter should remain asleep by default")

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fail_enqueue_chat_job)

    memory_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_user_message",
        lambda *args, **kwargs: memory_calls.append((args, kwargs)),
    )

    response = robot_service.handle_inbound_message(db, robot, _message("hello"))

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "conversation_sleeping"
    assert response.reply_chunks == []
    assert len(memory_calls) == 1
    assert str(memory_calls[0][0][0]) == str(robot.id)
    assert memory_calls[0][0][1] == "group:g1"
    assert memory_calls[0][0][2] == "hello"
    assert memory_calls[0][1]["sender"] == "onebot_v11:group:g1:u1"


def test_mentioned_group_message_routes_to_default_item_agent(
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
    memory_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_user_message",
        lambda *args, **kwargs: memory_calls.append((args, kwargs)),
    )


    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello", mentioned_bot=True),
    )

    assert response.success is True
    assert response.item_id == str(item.id)
    assert response.route_key == "alpha"
    assert captured["job"].message == "hello"
    assert captured["job"].conversation_key == "group:g1"
    assert captured["job"].sender_key == "onebot_v11:group:g1:u1"
    assert isinstance(captured["job"].reply_target, RobotReplyTarget)
    assert response.reply_chunks == []
    assert len(memory_calls) == 1
    assert str(memory_calls[0][0][0]) == str(robot.id)
    assert memory_calls[0][0][1] == "group:g1"
    assert memory_calls[0][0][2] == "hello"
    assert memory_calls[0][1]["sender"] == "onebot_v11:group:g1:u1"


def test_robot_explicit_memory_is_persisted_with_conversation_scope(
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
    persisted: list[tuple[str, object, object]] = []

    def fake_persist_memory_candidate(item_id, candidate, store):
        persisted.append((item_id, candidate, store))
        return "memory-1"

    monkeypatch.setattr(
        "app.services.agent.prompts.policy.persist_memory_candidate",
        fake_persist_memory_candidate,
    )

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "remember this: nickname is XiaoChai",
            target={"id": "g1"},
            mentioned_bot=True,
        ),
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["job"].conversation_key == "group:g1"
    assert len(persisted) == 1
    assert persisted[0][0] == str(item.id)
    candidate = persisted[0][1]
    assert candidate.content == "nickname is XiaoChai"
    assert candidate.memory_type == "fact"
    assert candidate.metadata["source"] == "qq_robot"
    assert candidate.metadata["robot_id"] == str(robot.id)
    assert candidate.metadata["conversation_key"] == "group:g1"
    assert candidate.metadata["robot_conversation_key"] == "group:g1"


def test_robot_auto_memory_high_confidence_is_persisted_with_sender_scope(
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

    _capture_queued_chat(monkeypatch)
    monkeypatch.setattr(vector_store, "get_all_memories", lambda *args, **kwargs: [])
    persisted: list[tuple[str, object, object]] = []

    def fake_persist_memory_candidate(item_id, candidate, store):
        persisted.append((item_id, candidate, store))
        return "memory-auto"

    monkeypatch.setattr(
        "app.services.agent.prompts.policy.persist_memory_candidate",
        fake_persist_memory_candidate,
    )

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "我喜欢短回复",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )

    assert response.success is True
    assert response.ignored is False
    assert len(persisted) == 1
    candidate = persisted[0][1]
    assert persisted[0][0] == str(item.id)
    assert candidate.memory_type == "preference"
    assert "Alice (u1)" in candidate.content
    assert "我喜欢短回复" in candidate.content
    assert candidate.metadata["source"] == "qq_robot_auto"
    assert candidate.metadata["robot_id"] == str(robot.id)
    assert candidate.metadata["conversation_key"] == "group:g1"
    assert candidate.metadata["robot_conversation_key"] == "group:g1"
    assert candidate.metadata["speaker"] == "Alice (u1)"
    assert candidate.metadata["observations"] == 1


def test_robot_auto_memory_low_confidence_promotes_after_repeat(
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

    _capture_queued_chat(monkeypatch)
    monkeypatch.setattr(vector_store, "get_all_memories", lambda *args, **kwargs: [])
    persisted: list[object] = []

    def fake_persist_memory_candidate(_item_id, candidate, store):
        persisted.append(candidate)
        return f"memory-{len(persisted)}"

    monkeypatch.setattr(
        "app.services.agent.prompts.policy.persist_memory_candidate",
        fake_persist_memory_candidate,
    )

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "最近在研究股票",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )
    assert first.success is True
    assert persisted == []

    second = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "最近在研究股票",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )
    assert second.success is True
    assert len(persisted) == 1
    candidate = persisted[0]
    assert candidate.memory_type == "context"
    assert "最近在研究股票" in candidate.content
    assert candidate.metadata["source"] == "qq_robot_auto_promoted"
    assert candidate.metadata["observations"] == 2
    assert candidate.metadata["conversation_key"] == "group:g1"


def test_robot_message_includes_current_conversation_impression_card(
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

    def fake_get_all_memories(item_id, memory_type=None):
        assert item_id == str(item.id)
        if memory_type != "preference":
            return []
        return [
            {
                "id": "current",
                "content": "用户偏好：Alice 喜欢短回复",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": str(robot.id),
                    "robot_conversation_key": "group:g1",
                    "updated_at": "2026-07-07T00:00:00",
                },
            },
            {
                "id": "same-speaker-other-group",
                "content": "用户偏好：Alice 以后叫她主人",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": str(robot.id),
                    "robot_conversation_key": "group:g2",
                    "speaker_global_key": "onebot_v11:user:u1",
                    "memory_scope": "speaker",
                    "updated_at": "2026-07-07T00:00:00",
                },
            },
            {
                "id": "other-group",
                "content": "other group secret",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": str(robot.id),
                    "robot_conversation_key": "group:g2",
                    "updated_at": "2026-07-07T00:00:00",
                },
            },
        ]

    monkeypatch.setattr(vector_store, "get_all_memories", fake_get_all_memories)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )

    assert response.success is True
    text = captured["job"].message
    assert "Current QQ conversation impression card" in text
    assert "Alice 喜欢短回复" in text
    assert "Alice 以后叫她主人" in text
    assert text.index("Alice 喜欢短回复") < text.index("Alice 以后叫她主人")
    assert "other group secret" not in text
    assert text.endswith("[Current QQ message]\nhello")
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

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
            mentioned_bot=True,
        ),
    )

    assert response.success is True
    text = captured["job"].message
    assert text.startswith(
        "[Robot message; conversation=group:g1; trigger=mention_bot; sender=Alice (u1)]\n"
    )
    assert "[Recent QQ live context; background only" not in text
    assert "Alice (u1): hello" not in text
    assert text.endswith("[Current QQ message]\nhello")
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

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
    text = captured["job"].message
    assert text.startswith(
        "[Robot message; conversation=private:u1; trigger=private_chat; sender=Alice (u1)]\n"
    )
    assert "[Recent QQ live context; background only" not in text
    assert "Alice (u1): hello" not in text
    assert text.endswith("[Current QQ message]\nhello")
    assert captured["job"].direct_reply_trigger is True
    assert captured["job"].reply_requires_awake is True
    assert captured["job"].conversation_generation > 0
    assert response.reply_chunks == []


def test_robot_message_includes_recent_live_context_without_current_duplicate(
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")
    monkeypatch.setattr(
        robot_conversation_memory,
        "read_recent",
        lambda *_args, **_kwargs: (
            "[2026-07-10T16:32:32+00:00] user FLY (2537134688): 换国内源吧\n"
            "[2026-07-10T16:33:33+00:00] user FLY (2537134688): 换好了吗"
        ),
    )

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "换好了吗",
            sender_key="onebot_v11:private:2537134688",
            target={"id": "2537134688", "private": True},
            sender={
                "user_id": "2537134688",
                "display_name": "FLY",
            },
        ),
    )

    assert response.success is True
    text = captured["job"].message
    assert "[Recent QQ live context; background only" in text
    assert "换国内源吧" in text
    assert text.count("换好了吗") == 1
    assert text.endswith("[Current QQ message]\n换好了吗")


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


def test_bot_at_prefix_does_not_break_term_command(
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
        _message(
            "[CQ:at,qq=10001] /term alpha status?",
            mentioned_bot=True,
            bot_self_ids=["10001"],
        ),
    )

    assert response.success is True
    assert response.item_id == str(item.id)
    assert response.route_key == "alpha"
    assert captured["job"].message == "status?"
    assert response.reply_chunks == []


def test_bot_at_prefix_is_preserved_for_chat_message(
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
            "[CQ:at,qq=10001] hello",
            mentioned_bot=True,
            bot_self_ids=["10001"],
        ),
    )

    assert response.success is True
    assert captured["job"].message == "[CQ:at,qq=10001] hello"
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


def test_configured_group_message_still_requires_awake_controller(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {"reply_message_types": ["group"]},
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
        raise AssertionError("sleeping group chat must not reach the agent")

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fail_enqueue_chat_job)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello group"),
    )

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "conversation_sleeping"
    assert response.reply_chunks == []
    snapshots = robot_service.conversation_controller_snapshots({robot.id})
    assert len(snapshots) == 1
    assert snapshots[0]["conversation_key"] == "group:g1"
    assert snapshots[0]["status"] == "sleeping"


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


def test_reply_message_type_filter_ignores_at_target_even_when_mention_match_mode_is_any(
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

    def fail_enqueue_chat_job(_job):
        raise AssertionError("@ target should not wake this robot")

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fail_enqueue_chat_job)

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello other mention",
            sender={
                "user_id": "2537134688",
                "display_name": "Alice",
            },
            conversation={"type": "group", "id": "369040885"},
            mentions=[
                {
                    "id": "1512220570",
                    "qq": "1512220570",
                    "name": "Bob",
                }
            ],
        ),
    )

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "reply_message_type_disabled"
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")
    before_activation = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain before", target={"id": "g1"}),
    )
    assert before_activation.ignored is True
    assert before_activation.reason == "conversation_sleeping"

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
    assert no_tool_reply.reason == "conversation_sleeping"

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
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[-1].conversation_key,
        robot_message_sent=True,
        reply_target=queued_jobs[-1].reply_target,
    )

    current_time["value"] = now + timedelta(seconds=30)

    expired = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain expired", target={"id": "g1"}),
    )
    assert expired.ignored is True
    assert expired.reason == "conversation_sleeping"


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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

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
    assert other_group.reason == "conversation_sleeping"

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
    assert other_private.ignored is False
    assert queued_jobs[-1].conversation_key == "private:u2"
    assert queued_jobs[-1].direct_reply_trigger is True
    assert queued_jobs[-1].reply_requires_awake is True

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
    same_group_job = queued_jobs[-1]
    assert queued_jobs[0].message.startswith(
        "[Robot message; conversation=group:g1; trigger=mention_bot; sender=Alice (u1)]\n"
    )
    assert "Alice (u1): hello mention" not in queued_jobs[0].message
    assert queued_jobs[0].message.endswith("[Current QQ message]\nhello mention")
    assert same_group_job.conversation_key == "group:g1"
    assert same_group_job.reply_context_active is True
    assert same_group_job.direct_reply_trigger is False
    assert "[Recent QQ conversation context" not in same_group_job.message
    assert "- Alice (u1): hello mention" not in same_group_job.message
    assert "plain in another group" not in same_group_job.message
    assert "plain in private" not in same_group_job.message
    assert same_group_job.message.startswith(
        "[Robot message; conversation=group:g1; trigger=active_chat_window; sender=Carol (u3)]\n"
    )

    assert same_group_job.message.endswith("[Current QQ message]\nplain in same group")


def test_direct_wakeup_agent_message_excludes_recent_same_conversation_context(
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    same_group_plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "plain before",
            sender_key="onebot_v11:group:g1:u1",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
        ),
    )
    assert same_group_plain.ignored is True

    other_group_plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "plain in another group",
            sender_key="onebot_v11:group:g2:u2",
            target={"id": "g2"},
            sender={"user_id": "u2", "display_name": "Eve"},
        ),
    )
    assert other_group_plain.ignored is True

    mentioned = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello mention",
            sender_key="onebot_v11:group:g1:u3",
            target={"id": "g1"},
            sender={"user_id": "u3", "display_name": "Bob"},
            mentioned_bot=True,
        ),
    )

    assert mentioned.ignored is False
    assert len(queued_jobs) == 1
    assert "[Recent QQ conversation context" not in queued_jobs[0].message
    assert "[Recent QQ live context; background only" not in queued_jobs[0].message
    assert "Alice (u1): plain before" not in queued_jobs[0].message
    assert "plain in another group" not in queued_jobs[0].message
    assert queued_jobs[0].message.startswith(
        "[Robot message; conversation=group:g1; trigger=mention_bot; sender=Bob (u3)]\n"
    )
    assert queued_jobs[0].message.endswith("[Current QQ message]\nhello mention")

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


def test_conversation_controller_rejects_stale_generation_after_sleep(
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention", target={"id": "g1"}, mentioned_bot=True),
    )
    assert first.ignored is False
    first_job = queued_jobs[-1]
    first_generation = first_job.conversation_generation
    assert first_job.reply_requires_awake is True
    assert first_generation > 0
    assert robot_service.conversation_controller_allows_reply(
        robot.id,
        first_job.conversation_key,
        first_generation,
        requires_awake=True,
    )

    robot_service._apply_reply_context_result(
        robot,
        first_job.conversation_key,
        robot_message_sent=True,
        reply_target=first_job.reply_target,
        conversation_generation=first_generation,
    )
    current_time["value"] = now + timedelta(seconds=30)

    assert not robot_service.conversation_controller_allows_reply(
        robot.id,
        first_job.conversation_key,
        first_generation,
        requires_awake=True,
    )

    second = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello again", target={"id": "g1"}, mentioned_bot=True),
    )
    assert second.ignored is False
    second_job = queued_jobs[-1]
    assert second_job.conversation_generation > first_generation
    assert not robot_service.conversation_controller_allows_reply(
        robot.id,
        first_job.conversation_key,
        first_generation,
        requires_awake=True,
    )
    assert robot_service.conversation_controller_allows_reply(
        robot.id,
        second_job.conversation_key,
        second_job.conversation_generation,
        requires_awake=True,
    )


def test_private_message_wakes_its_conversation_controller(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["private"],
            "reply_context_window_seconds": 10,
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

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello private",
            sender_key="onebot_v11:private:u1",
            target={"id": "u1", "private": True},
            sender={"user_id": "u1", "display_name": "Alice"},
        ),
    )
    assert first.ignored is False
    first_job = queued_jobs[-1]
    assert first_job.conversation_key == "private:u1"
    assert first_job.direct_reply_trigger is True
    assert first_job.reply_requires_awake is True
    assert first_job.conversation_generation > 0

    robot_service._apply_reply_context_result(
        robot,
        first_job.conversation_key,
        robot_message_sent=True,
        reply_target=first_job.reply_target,
        conversation_generation=first_job.conversation_generation,
    )

    robot_service.sleep_conversation_controller(
        robot.id,
        first_job.conversation_key,
        reason="test_private_sleep",
    )
    assert not robot_service.conversation_controller_allows_reply(
        robot.id,
        first_job.conversation_key,
        first_job.conversation_generation,
        requires_awake=True,
    )

    wake = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "hello again",
            sender_key="onebot_v11:private:u1",
            target={"id": "u1", "private": True},
            sender={"user_id": "u1", "display_name": "Alice"},
        ),
    )
    assert wake.ignored is False
    assert len(queued_jobs) == 2
    assert queued_jobs[-1].conversation_generation > first_job.conversation_generation


def test_direct_wakeup_job_reaches_agent_even_if_controller_window_expires(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 10,
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("wake after delay", target={"id": "g1"}, mentioned_bot=True),
    )
    assert response.ignored is False
    job = queued_jobs[-1]
    assert job.direct_reply_trigger is True
    assert job.reply_requires_awake is True

    current_time["value"] = now + timedelta(seconds=11)
    captured_messages: list[str] = []

    async def fake_chat_with_item(**kwargs):
        captured_messages.append(str(kwargs["message"]))
        return ChatResponseResult(content="", robot_message_sent=False)

    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)

    robot_service._process_chat_job(job)

    assert captured_messages == [job.message]



def test_visible_agent_response_without_robot_tool_is_sent_to_qq(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 10,
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
    sent_messages: list[tuple[Any, Any, str]] = []

    def fake_enqueue_chat_job(job) -> bool:
        queued_jobs.append(job)
        return True

    def fake_send_message(robot_id, target, text) -> None:
        sent_messages.append((robot_id, target, text))

    async def fake_chat_with_item(**_kwargs):
        return ChatResponseResult(content="install done", robot_message_sent=False)

    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")
    monkeypatch.setattr(robot_service, "_chat_with_item", fake_chat_with_item)
    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("install done?", target={"id": "g1"}, mentioned_bot=True),
    )
    assert response.ignored is False
    job = queued_jobs[-1]

    robot_service._process_chat_job(job)

    assert sent_messages == [(robot.id, job.reply_target, "install done")]
    assert robot_service.conversation_controller_allows_reply(
        robot.id,
        job.conversation_key,
        job.conversation_generation,
        requires_awake=True,
    )


def test_direct_wakeup_countdown_starts_after_agent_result(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 10,
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("wake before countdown", target={"id": "g1"}, mentioned_bot=True),
    )
    assert response.ignored is False
    job = queued_jobs[-1]
    assert job.direct_reply_trigger is True
    assert job.reply_requires_awake is True

    processing_snapshot = robot_service.conversation_controller_snapshots({robot.id})[0]
    assert processing_snapshot["conversation_key"] == "group:g1"
    assert processing_snapshot["status"] == "processing"
    assert processing_snapshot["awake"] is True
    assert processing_snapshot["processing"] is True
    assert processing_snapshot["expires_at"] is None
    assert processing_snapshot["seconds_remaining"] == 0

    current_time["value"] = now + timedelta(seconds=11)
    assert robot_service.conversation_controller_allows_reply(
        robot.id,
        job.conversation_key,
        job.conversation_generation,
        requires_awake=True,
    )

    robot_service._apply_reply_context_result(
        robot,
        job.conversation_key,
        robot_message_sent=True,
        reply_target=job.reply_target,
        conversation_generation=job.conversation_generation,
    )

    awake_snapshot = robot_service.conversation_controller_snapshots({robot.id})[0]
    assert awake_snapshot["status"] == "awake"
    assert awake_snapshot["awake"] is True
    assert awake_snapshot["processing"] is False
    assert awake_snapshot["expires_at"] is not None
    assert awake_snapshot["seconds_remaining"] == 10

    current_time["value"] = now + timedelta(seconds=22)
    assert not robot_service.conversation_controller_allows_reply(
        robot.id,
        job.conversation_key,
        job.conversation_generation,
        requires_awake=True,
    )
    sleeping_snapshot = robot_service.conversation_controller_snapshots({robot.id})[0]
    assert sleeping_snapshot["status"] == "sleeping"
    assert sleeping_snapshot["awake"] is False
    assert sleeping_snapshot["processing"] is False




def test_messages_arriving_while_processing_are_batched_in_pending_queue(
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")
    monkeypatch.setattr(robot_service, "_persist_inbound_long_term_memory", lambda **_: None)
    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "第一个问题",
            sender_key="onebot_v11:group:g1:u1",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )
    assert first.ignored is False
    first_job = queued_jobs[-1]

    second = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "第二个人也问",
            sender_key="onebot_v11:group:g1:u2",
            target={"id": "g1"},
            sender={"user_id": "u2", "display_name": "Bob"},
            mentioned_bot=True,
        ),
    )
    third = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "第三个人继续问",
            sender_key="onebot_v11:group:g1:u3",
            target={"id": "g1"},
            sender={"user_id": "u3", "display_name": "Carol"},
            mentioned_bot=True,
        ),
    )

    assert second.reason == "queued_pending"
    assert third.reason == "queued_pending"
    assert len(queued_jobs) == 1

    robot_service._apply_reply_context_result(
        robot,
        first_job.conversation_key,
        robot_message_sent=True,
        reply_target=first_job.reply_target,
        conversation_generation=first_job.conversation_generation,
    )
    assert robot_service._enqueue_pending_chat_followup(
        robot=robot,
        conversation_key=first_job.conversation_key,
    ) is True

    assert len(queued_jobs) == 2
    pending_job = queued_jobs[-1]
    assert pending_job.reply_context_active is True
    assert pending_job.direct_reply_trigger is False
    assert "trigger=pending_queue" in pending_job.message
    assert "[Pending QQ messages; answer each unanswered item in order]" in pending_job.message
    assert "1. sender=Bob (u2); trigger=mention_bot: 第二个人也问" in pending_job.message
    assert "2. sender=Carol (u3); trigger=mention_bot: 第三个人继续问" in pending_job.message
    assert pending_job.message.index("第二个人也问") < pending_job.message.index("第三个人继续问")


def test_direct_wakeup_pending_messages_continue_after_first_job_sends_no_reply(
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
    monkeypatch.setattr(robot_service, "_enqueue_chat_job", lambda job: queued_jobs.append(job) or True)
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")
    monkeypatch.setattr(robot_service, "_persist_inbound_long_term_memory", lambda **_: None)

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "第一个唤醒",
            sender_key="onebot_v11:group:g1:u1",
            target={"id": "g1"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )
    assert first.ignored is False
    first_job = queued_jobs[-1]

    active_plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "旁边人闲聊一句",
            sender_key="onebot_v11:group:g1:u2",
            target={"id": "g1"},
            sender={"user_id": "u2", "display_name": "Bob"},
        ),
    )
    second_wakeup = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "第二个人也叫你",
            sender_key="onebot_v11:group:g1:u3",
            target={"id": "g1"},
            sender={"user_id": "u3", "display_name": "Carol"},
            mentioned_bot=True,
        ),
    )
    third_wakeup = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "第三个人继续叫你",
            sender_key="onebot_v11:group:g1:u4",
            target={"id": "g1"},
            sender={"user_id": "u4", "display_name": "Dave"},
            mentioned_bot=True,
        ),
    )

    assert active_plain.reason == "queued_pending"
    assert second_wakeup.reason == "queued_pending"
    assert third_wakeup.reason == "queued_pending"
    assert len(queued_jobs) == 1

    robot_service._apply_reply_context_result(
        robot,
        first_job.conversation_key,
        robot_message_sent=False,
        reply_target=first_job.reply_target,
        conversation_generation=first_job.conversation_generation,
    )
    assert robot_service._enqueue_pending_chat_followup(
        robot=robot,
        conversation_key=first_job.conversation_key,
        direct_wakeup_only=True,
    ) is True

    assert len(queued_jobs) == 2
    pending_message = queued_jobs[-1].message
    assert "trigger=pending_queue" in pending_message
    assert "旁边人闲聊一句" not in pending_message
    assert "1. sender=Carol (u3); trigger=mention_bot: 第二个人也叫你" in pending_message
    assert "2. sender=Dave (u4); trigger=mention_bot: 第三个人继续叫你" in pending_message
    assert pending_message.index("第二个人也叫你") < pending_message.index("第三个人继续叫你")
def test_pure_qq_image_message_is_ignored_before_agent_dispatch(
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

    queued_jobs: list[Any] = []
    monkeypatch.setattr(robot_service, "_enqueue_chat_job", lambda job: queued_jobs.append(job) or True)
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "[CQ:image,summary=&#91;animation&#93;,file=emoji.jpg,url=https://example.test/a.jpg]",
            target={"id": "g-image-only"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
        ),
    )

    assert response.success is True
    assert response.ignored is True
    assert response.reason == "media_message_ignored"
    assert queued_jobs == []


def test_qq_image_segments_are_removed_from_agent_and_pending_messages(
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
    monkeypatch.setattr(robot_service, "_enqueue_chat_job", lambda job: queued_jobs.append(job) or True)
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")
    monkeypatch.setattr(robot_service, "_persist_inbound_long_term_memory", lambda **_: None)

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "[CQ:at,qq=10001] first [CQ:image,file=first.jpg,url=https://example.test/first.jpg] question",
            sender_key="onebot_v11:group:g-image-mixed:u1",
            target={"id": "g-image-mixed"},
            sender={"user_id": "u1", "display_name": "Alice"},
            mentioned_bot=True,
            bot_self_ids=["10001"],
        ),
    )
    assert first.ignored is False
    assert len(queued_jobs) == 1
    first_job = queued_jobs[-1]
    assert "[CQ:image" not in first_job.message
    assert first_job.message.endswith(
        "[Current QQ message]\n[CQ:at,qq=10001] first question"
    )

    image_only = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "[CQ:image,summary=&#91;animation&#93;,file=emoji.jpg,url=https://example.test/emoji.jpg]",
            sender_key="onebot_v11:group:g-image-mixed:u2",
            target={"id": "g-image-mixed"},
            sender={"user_id": "u2", "display_name": "Bob"},
        ),
    )
    assert image_only.ignored is True
    assert image_only.reason == "media_message_ignored"
    assert len(queued_jobs) == 1

    mixed_pending = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "look [CQ:image,file=pending.jpg,url=https://example.test/pending.jpg] now",
            sender_key="onebot_v11:group:g-image-mixed:u3",
            target={"id": "g-image-mixed"},
            sender={"user_id": "u3", "display_name": "Carol"},
        ),
    )
    assert mixed_pending.reason == "queued_pending"

    robot_service._apply_reply_context_result(
        robot,
        first_job.conversation_key,
        robot_message_sent=True,
        reply_target=first_job.reply_target,
        conversation_generation=first_job.conversation_generation,
    )
    assert robot_service._enqueue_pending_chat_followup(
        robot=robot,
        conversation_key=first_job.conversation_key,
    ) is True

    assert len(queued_jobs) == 2
    pending_message = queued_jobs[-1].message
    assert "[CQ:image" not in pending_message
    assert "1. sender=Carol (u3); trigger=active_chat_window: look now" in pending_message


def test_pending_chat_queue_keeps_latest_five_messages(
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
    monkeypatch.setattr(robot_service, "_enqueue_chat_job", lambda job: queued_jobs.append(job) or True)
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")
    monkeypatch.setattr(robot_service, "_persist_inbound_long_term_memory", lambda **_: None)
    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "正在处理的第一条",
            sender_key="onebot_v11:group:g1:u0",
            target={"id": "g1"},
            sender={"user_id": "u0", "display_name": "User0"},
            mentioned_bot=True,
        ),
    )
    assert first.ignored is False
    first_job = queued_jobs[-1]

    for index in range(1, 8):
        response = robot_service.handle_inbound_message(
            db,
            robot,
            _message(
                f"pending {index}",
                sender_key=f"onebot_v11:group:g1:u{index}",
                target={"id": "g1"},
                sender={"user_id": f"u{index}", "display_name": f"User{index}"},
                mentioned_bot=True,
            ),
        )
        assert response.reason == "queued_pending"

    robot_service._apply_reply_context_result(
        robot,
        first_job.conversation_key,
        robot_message_sent=True,
        reply_target=first_job.reply_target,
        conversation_generation=first_job.conversation_generation,
    )
    assert robot_service._enqueue_pending_chat_followup(
        robot=robot,
        conversation_key=first_job.conversation_key,
    ) is True

    assert len(queued_jobs) == 2
    message = queued_jobs[-1].message
    assert "pending 1" not in message
    assert "pending 2" not in message
    for index in range(3, 8):
        assert f"pending {index}" in message
    assert message.count("trigger=mention_bot: pending") == 5
def test_processing_controller_timeout_sleeps_group_and_blocks_plain_message(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["group", "mention"],
            "reply_context_window_seconds": 10,
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("wake and then stall", target={"id": "g1"}, mentioned_bot=True),
    )
    assert response.ignored is False
    job = queued_jobs[-1]

    processing_snapshot = robot_service.conversation_controller_snapshots({robot.id})[0]
    assert processing_snapshot["status"] == "processing"
    assert processing_snapshot["processing_expires_at"] is not None

    current_time["value"] = now + timedelta(seconds=121)
    plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message("ordinary group chatter", target={"id": "g1"}),
    )
    assert plain.success is True
    assert plain.ignored is True
    assert plain.reason == "conversation_sleeping"
    assert not robot_service.conversation_controller_allows_reply(
        robot.id,
        job.conversation_key,
        job.conversation_generation,
        requires_awake=True,
    )

    sleeping_snapshot = robot_service.conversation_controller_snapshots({robot.id})[0]
    assert sleeping_snapshot["status"] == "sleeping"
    assert sleeping_snapshot["awake"] is False
    assert sleeping_snapshot["sleeping"] is True


def test_agent_no_reply_clears_controller_as_sleeping_gate(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["group", "mention"],
            "reply_context_window_seconds": 10,
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("wake but no reply", target={"id": "g1"}, mentioned_bot=True),
    )
    assert response.ignored is False
    job = queued_jobs[-1]

    robot_service._apply_reply_context_result(
        robot,
        job.conversation_key,
        robot_message_sent=False,
        reply_target=job.reply_target,
        conversation_generation=job.conversation_generation,
    )

    plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message("ordinary group chatter", target={"id": "g1"}),
    )
    assert plain.success is True
    assert plain.ignored is True
    assert plain.reason == "conversation_sleeping"
    assert len(queued_jobs) == 1


def test_reply_context_expiry_sleeps_group_conversation_until_direct_wakeup(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["group", "mention"],
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention", target={"id": "g1"}, mentioned_bot=True),
    )
    assert first.ignored is False
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[-1].conversation_key,
        robot_message_sent=True,
        reply_target=queued_jobs[-1].reply_target,
        conversation_generation=queued_jobs[-1].conversation_generation,
    )

    current_time["value"] = now + timedelta(seconds=30)
    stale_plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message("plain after idle", target={"id": "g1"}),
    )
    assert stale_plain.success is True
    assert stale_plain.ignored is True
    assert stale_plain.reason == "conversation_sleeping"
    assert len(queued_jobs) == 1

    wake = robot_service.handle_inbound_message(
        db,
        robot,
        _message("wake again", target={"id": "g1"}, mentioned_bot=True),
    )
    assert wake.ignored is False
    assert len(queued_jobs) == 2
    assert queued_jobs[-1].conversation_generation > queued_jobs[0].conversation_generation


def test_active_chat_window_no_reply_sleeps_group_controller_until_direct_wakeup(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["group", "mention"],
            "reply_context_window_seconds": 10,
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention", target={"id": "g1"}, mentioned_bot=True),
    )
    assert first.ignored is False
    first_job = queued_jobs[-1]
    robot_service._apply_reply_context_result(
        robot,
        first_job.conversation_key,
        robot_message_sent=True,
        reply_target=first_job.reply_target,
        conversation_generation=first_job.conversation_generation,
    )

    active_plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message("ordinary group chatter", target={"id": "g1"}),
    )
    assert active_plain.ignored is False
    assert len(queued_jobs) == 2
    active_job = queued_jobs[-1]
    assert active_job.reply_context_active is True
    assert active_job.direct_reply_trigger is False

    robot_service._apply_reply_context_result(
        robot,
        active_job.conversation_key,
        robot_message_sent=False,
        reply_target=active_job.reply_target,
        conversation_generation=active_job.conversation_generation,
        sleep_when_no_reply=True,
    )

    sleeping_plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message("more ordinary group chatter", target={"id": "g1"}),
    )
    assert sleeping_plain.success is True
    assert sleeping_plain.ignored is True
    assert sleeping_plain.reason == "conversation_sleeping"
    assert len(queued_jobs) == 2
    assert not robot_service.conversation_controller_allows_reply(
        robot.id,
        active_job.conversation_key,
        active_job.conversation_generation,
        requires_awake=True,
    )

    wake = robot_service.handle_inbound_message(
        db,
        robot,
        _message("wake again", target={"id": "g1"}, mentioned_bot=True),
    )
    assert wake.ignored is False
    assert len(queued_jobs) == 3
    assert queued_jobs[-1].conversation_generation > active_job.conversation_generation


def test_conversation_controller_snapshot_reports_awake_then_sleeping(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["mention"],
            "reply_context_window_seconds": 10,
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention", target={"id": "g1"}, mentioned_bot=True),
    )
    assert response.ignored is False
    job = queued_jobs[-1]
    robot_service._apply_reply_context_result(
        robot,
        job.conversation_key,
        robot_message_sent=True,
        reply_target=job.reply_target,
        conversation_generation=job.conversation_generation,
    )

    awake_snapshot = robot_service.conversation_controller_snapshots({robot.id})[0]
    assert awake_snapshot["robot_id"] == str(robot.id)
    assert awake_snapshot["conversation_key"] == "group:g1"
    assert awake_snapshot["conversation_type"] == "group"
    assert awake_snapshot["conversation_id"] == "g1"
    assert awake_snapshot["item_id"] == str(item.id)
    assert awake_snapshot["status"] == "awake"
    assert awake_snapshot["awake"] is True
    assert awake_snapshot["sleeping"] is False
    assert awake_snapshot["seconds_remaining"] == 10
    assert robot_service.conversation_controller_snapshots(
        {robot.id},
        item_ids={create_random_item(db).id},
    ) == []

    current_time["value"] = now + timedelta(seconds=11)
    sleeping_snapshot = robot_service.conversation_controller_snapshots({robot.id})[0]
    assert sleeping_snapshot["status"] == "sleeping"
    assert sleeping_snapshot["awake"] is False
    assert sleeping_snapshot["sleeping"] is True
    assert sleeping_snapshot["expires_at"] is None
    assert sleeping_snapshot["seconds_remaining"] == 0
    assert sleeping_snapshot["generation"] > job.conversation_generation


def test_sleep_command_blocks_group_messages_until_direct_wakeup(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    robot.config = {
        "credentials": dict(robot.config.get("credentials", {})),
        "options": {
            "reply_message_types": ["group", "mention"],
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
    monkeypatch.setattr(robot_service, "_conversation_impression_card", lambda **_: "")

    first = robot_service.handle_inbound_message(
        db,
        robot,
        _message("hello mention", target={"id": "g1"}, mentioned_bot=True),
    )
    assert first.ignored is False
    robot_service._apply_reply_context_result(
        robot,
        queued_jobs[-1].conversation_key,
        robot_message_sent=True,
        reply_target=queued_jobs[-1].reply_target,
        conversation_generation=queued_jobs[-1].conversation_generation,
    )

    sleep = robot_service.handle_inbound_message(
        db,
        robot,
        _message("\u4f11\u7720\u53bb", target={"id": "g1"}, replied_to_bot=True),
    )
    assert sleep.success is True
    assert sleep.ignored is True
    assert sleep.reason == "sleep_command"
    assert len(queued_jobs) == 1

    sleeping_plain = robot_service.handle_inbound_message(
        db,
        robot,
        _message("\u4f46\u662f\u4e00\u76f4\u6da8\u600e\u4e48\u4e70\uff1f", target={"id": "g1"}),
    )
    assert sleeping_plain.success is True
    assert sleeping_plain.ignored is True
    assert sleeping_plain.reason == "conversation_sleeping"
    assert len(queued_jobs) == 1

    wake = robot_service.handle_inbound_message(
        db,
        robot,
        _message("\u9192\u9192", target={"id": "g1"}, mentioned_bot=True),
    )
    assert wake.ignored is False
    assert len(queued_jobs) == 2
    assert queued_jobs[-1].conversation_generation > queued_jobs[0].conversation_generation

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
    assert no_tool_follow_up.reason == "conversation_sleeping"

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
        _message("hello", mentioned_bot=True),
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
