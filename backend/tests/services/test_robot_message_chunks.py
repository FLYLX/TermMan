import json
import uuid

from app.plugins.robot.bridge_client import RobotBridgeClient
from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.message_chunks import (
    is_group_reply_target,
    split_robot_message_for_target,
)


def test_group_target_detects_explicit_and_universal_metadata() -> None:
    assert is_group_reply_target(RobotReplyTarget(target_type="group", target_id="123"))
    assert is_group_reply_target(
        RobotReplyTarget(
            target_type="universal",
            target_id="123",
            metadata={"conversation": {"type": "group", "id": "123"}},
        )
    )
    assert not is_group_reply_target(
        RobotReplyTarget(
            target_type="universal",
            target_id="456",
            metadata={"conversation": {"type": "private", "id": "456"}},
        )
    )


def test_group_message_is_split_into_short_chunks() -> None:
    target = RobotReplyTarget(target_type="group", target_id="123")
    text = "第一句先简单回应一下。第二句补一点上下文。第三句再给一个可以执行的建议。"

    chunks = split_robot_message_for_target(target, text, max_chars=18)

    assert chunks == [text]


def test_group_message_strips_terminal_period_for_casual_reply() -> None:
    target = RobotReplyTarget(target_type="group", target_id="123")

    assert split_robot_message_for_target(target, "在。") == ["在。"]


def test_group_message_text_is_not_split_by_explicit_lines() -> None:
    target = RobotReplyTarget(target_type="group", target_id="123")
    text = "在\n我先看一下\n等我一下"

    chunks = split_robot_message_for_target(target, text)

    assert chunks == [text]


def test_private_message_is_not_split() -> None:
    target = RobotReplyTarget(target_type="private", target_id="456")
    text = "第一句先简单回应一下。第二句补一点上下文。第三句再给一个可以执行的建议。"

    assert split_robot_message_for_target(target, text, max_chars=18) == [text]


def test_bridge_client_sends_group_chunks_in_order(monkeypatch) -> None:
    client = RobotBridgeClient()
    target = RobotReplyTarget(target_type="group", target_id="123")
    text = "第一句先简单回应一下。第二句补一点上下文。第三句再给一个可以执行的建议。" * 3
    calls: list[dict] = []

    def fake_request(method, path, *, timeout, content):
        calls.append(
            {
                "method": method,
                "path": path,
                "timeout": timeout,
                "body": json.loads(content),
            }
        )

    monkeypatch.setattr(client, "_request", fake_request)

    client.send_message(uuid.uuid4(), target, text)

    sent_texts = [call["body"]["text"] for call in calls]
    assert sent_texts == [text]
    assert all(call["path"] == "/internal/send" for call in calls)


def test_bridge_client_keeps_single_text_as_one_group_message(monkeypatch) -> None:
    client = RobotBridgeClient()
    target = RobotReplyTarget(target_type="group", target_id="123")
    calls: list[dict] = []

    def fake_request(method, path, *, timeout, content):
        calls.append(
            {
                "method": method,
                "path": path,
                "timeout": timeout,
                "body": json.loads(content),
            }
        )

    monkeypatch.setattr(client, "_request", fake_request)

    client.send_message(
        uuid.uuid4(),
        target,
        "我先看一下，可能是桥接服务还没接上，等我确认一下状态",
    )

    assert [call["body"]["text"] for call in calls] == [
        "我先看一下，可能是桥接服务还没接上，等我确认一下状态",
    ]
    assert len(calls) == 1
    assert all(call["path"] == "/internal/send" for call in calls)


def test_bridge_client_compacts_paragraph_breaks_inside_one_message(monkeypatch) -> None:
    client = RobotBridgeClient()
    target = RobotReplyTarget(target_type="group", target_id="123")
    calls: list[dict] = []

    def fake_request(method, path, *, timeout, content):
        calls.append(
            {
                "method": method,
                "path": path,
                "timeout": timeout,
                "body": json.loads(content),
            }
        )

    monkeypatch.setattr(client, "_request", fake_request)

    client.send_message(uuid.uuid4(), target, "我先看一下\n\n可能是桥接还没接上")

    assert [call["body"]["text"] for call in calls] == [
        "我先看一下可能是桥接还没接上"
    ]
    assert len(calls) == 1


def test_bridge_client_blocks_internal_tool_trace(monkeypatch) -> None:
    client = RobotBridgeClient()
    target = RobotReplyTarget(target_type="group", target_id="123")
    calls: list[dict] = []

    def fake_request(method, path, *, timeout, content):
        calls.append(
            {
                "method": method,
                "path": path,
                "timeout": timeout,
                "body": json.loads(content),
            }
        )

    monkeypatch.setattr(client, "_request", fake_request)

    client.send_message(
        uuid.uuid4(),
        target,
        "Executing tool: mcp_robot_send_message\n\n"
        "Message sent to current robot conversation.",
    )

    assert calls == []


def test_bridge_client_sanitizes_mixed_internal_tool_trace(monkeypatch) -> None:
    client = RobotBridgeClient()
    target = RobotReplyTarget(target_type="private", target_id="456")
    calls: list[dict] = []

    def fake_request(method, path, *, timeout, content):
        calls.append(
            {
                "method": method,
                "path": path,
                "timeout": timeout,
                "body": json.loads(content),
            }
        )

    monkeypatch.setattr(client, "_request", fake_request)

    client.send_message(
        uuid.uuid4(),
        target,
        "在呢。需要做什么测试？\n\n"
        "Executing tool: mcp_robot_send_message\n\n"
        "Message sent to current robot conversation.\n\n"
        "[no_qq_reply]",
    )

    assert [call["body"]["text"] for call in calls] == ["在呢。需要做什么测试？"]
