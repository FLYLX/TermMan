from app.plugins.robot.contracts import RobotReplyTarget
from app.services.agent.mcp.robot_context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.mcp.robot_server import RobotMCPServer


def test_robot_mcp_send_message_requires_context_or_explicit_target() -> None:
    server = RobotMCPServer()

    result = server.call_tool("send_message", {"text": "hello"})

    assert result[0]["type"] == "text"
    assert "no active robot conversation context" in result[0]["text"]
    assert "target_type and target_id" in result[0]["text"]


def test_robot_mcp_send_message_uses_explicit_target(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: dict[str, object] = {}

    def fake_send_message(robot_id, reply_target, text):
        sent["robot_id"] = robot_id
        sent["reply_target"] = reply_target
        sent["text"] = text

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    monkeypatch.setattr(
        server,
        "_get_accessible_robot_id",
        lambda args, fallback_robot_id="": "robot-2",
    )

    result = server.call_tool(
        "send_message",
        {
            "text": "notify group",
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "Message sent to QQ group 123456."}
    ]
    assert sent["robot_id"] == "robot-2"
    assert sent["text"] == "notify group"
    assert isinstance(sent["reply_target"], RobotReplyTarget)
    assert sent["reply_target"].target_type == "group"
    assert sent["reply_target"].target_id == "123456"


def test_robot_mcp_send_message_accepts_stamped_target_aliases(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: list[tuple[str, RobotReplyTarget, str]] = []

    def fake_send_message(robot_id, reply_target, text):
        sent.append((robot_id, reply_target, text))

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    monkeypatch.setattr(
        server,
        "_get_accessible_robot_id",
        lambda args, fallback_robot_id="": "robot-2",
    )

    alias_result = server.call_tool(
        "send_message",
        {
            "text": "alias target",
            "mcp_target_type": "private",
            "mcp_target_id": "654321",
            "_termman_user_id": "user-1",
        },
    )
    conversation_result = server.call_tool(
        "send_message",
        {
            "text": "conversation target",
            "conversation": "group:123456",
            "_termman_user_id": "user-1",
            "_robot_known_targets": [
                {
                    "conversation": "group:123456",
                    "target_type": "group",
                    "target_id": "123456",
                    "sender": "Alice (10001)",
                }
            ],
        },
    )

    assert alias_result == [
        {"type": "text", "text": "Message sent to QQ private 654321."}
    ]
    assert conversation_result == [
        {
            "type": "text",
            "text": "Message sent to QQ group 123456 from chat context.",
        }
    ]
    assert [(robot_id, target.target_type, target.target_id, text) for robot_id, target, text in sent] == [
        ("robot-2", "private", "654321", "alias target"),
        ("robot-2", "group", "123456", "conversation target"),
    ]


def test_robot_mcp_send_message_resolves_target_from_context_reply_to(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: dict[str, object] = {}

    def fake_send_message(robot_id, reply_target, text):
        sent["robot_id"] = robot_id
        sent["reply_target"] = reply_target
        sent["text"] = text

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    monkeypatch.setattr(
        server,
        "_get_accessible_robot_id",
        lambda args, fallback_robot_id="": fallback_robot_id or "robot-2",
    )

    result = server.call_tool(
        "send_message",
        {
            "text": "tell Alice",
            "reply_to": "Alice",
            "_termman_user_id": "user-1",
            "_robot_known_targets": [
                {
                    "conversation": "group:123456",
                    "target_type": "group",
                    "target_id": "123456",
                    "sender": "Alice (10001)",
                    "robot_id": "robot-1",
                },
                {
                    "conversation": "private:654321",
                    "target_type": "private",
                    "target_id": "654321",
                    "sender": "Bob (654321)",
                    "robot_id": "robot-1",
                },
            ],
        },
    )

    assert result == [
        {"type": "text", "text": "Message sent to QQ group 123456 from chat context."}
    ]
    assert sent["robot_id"] == "robot-1"
    assert sent["text"] == "tell Alice"
    assert isinstance(sent["reply_target"], RobotReplyTarget)
    assert sent["reply_target"].target_type == "group"
    assert sent["reply_target"].target_id == "123456"


def test_robot_mcp_send_message_uses_only_context_target_without_reply_to(
    monkeypatch,
) -> None:
    server = RobotMCPServer()
    sent: dict[str, object] = {}

    def fake_send_message(robot_id, reply_target, text):
        sent["robot_id"] = robot_id
        sent["reply_target"] = reply_target
        sent["text"] = text

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    monkeypatch.setattr(
        server,
        "_get_accessible_robot_id",
        lambda args, fallback_robot_id="": fallback_robot_id or "robot-2",
    )

    result = server.call_tool(
        "send_message",
        {
            "text": "single target",
            "_termman_user_id": "user-1",
            "_robot_known_targets": [
                {
                    "conversation": "private:654321",
                    "target_type": "private",
                    "target_id": "654321",
                    "sender": "Bob (654321)",
                    "robot_id": "robot-1",
                }
            ],
        },
    )

    assert result == [
        {
            "type": "text",
            "text": "Message sent to QQ private 654321 from chat context.",
        }
    ]
    assert sent["robot_id"] == "robot-1"
    assert isinstance(sent["reply_target"], RobotReplyTarget)
    assert sent["reply_target"].target_type == "private"
    assert sent["reply_target"].target_id == "654321"


def test_robot_mcp_send_message_uses_registered_context(monkeypatch) -> None:
    server = RobotMCPServer()
    target = RobotReplyTarget(
        target_type="universal",
        target_id="group-1",
        metadata={"target": {"id": "group-1"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:group-1:user-1",
            reply_target=target,
        )
    )
    sent: dict[str, object] = {}

    def fake_send_message(robot_id, reply_target, text):
        sent["robot_id"] = robot_id
        sent["reply_target"] = reply_target
        sent["text"] = text

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        result = server.call_tool(
            "send_message",
            {"text": "notify user", "_robot_context_token": token},
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result == [
        {"type": "text", "text": "Message sent to current robot conversation."}
    ]
    assert sent["robot_id"] == "robot-1"
    assert sent["text"] == "notify user"
    assert isinstance(sent["reply_target"], RobotReplyTarget)
    assert sent["reply_target"].target_id == "group-1"


def test_robot_mcp_send_message_prefers_active_context_over_ambiguous_history(
    monkeypatch,
) -> None:
    server = RobotMCPServer()
    target = RobotReplyTarget(
        target_type="group",
        target_id="current-group",
        metadata={"target": {"id": "current-group"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-current",
            sender_key="onebot_v11:group:current-group:user-1",
            reply_target=target,
        )
    )
    sent: dict[str, object] = {}

    def fake_send_message(robot_id, reply_target, text):
        sent["robot_id"] = robot_id
        sent["reply_target"] = reply_target
        sent["text"] = text

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        result = server.call_tool(
            "send_message",
            {
                "text": "reply current chat",
                "_robot_context_token": token,
                "_robot_known_targets": [
                    {
                        "conversation": "group:other-group",
                        "target_type": "group",
                        "target_id": "other-group",
                        "sender": "Alice (10001)",
                        "robot_id": "robot-current",
                    },
                    {
                        "conversation": "private:654321",
                        "target_type": "private",
                        "target_id": "654321",
                        "sender": "Bob (654321)",
                        "robot_id": "robot-current",
                    },
                ],
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result == [
        {"type": "text", "text": "Message sent to current robot conversation."}
    ]
    assert sent["robot_id"] == "robot-current"
    assert sent["text"] == "reply current chat"
    assert isinstance(sent["reply_target"], RobotReplyTarget)
    assert sent["reply_target"].target_type == "group"
    assert sent["reply_target"].target_id == "current-group"


def test_robot_mcp_send_message_broadcasts_to_context_targets(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: list[tuple[str, str, str, str]] = []

    def fake_send_message(robot_id, reply_target, text):
        sent.append((robot_id, reply_target.target_type, reply_target.target_id, text))

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    monkeypatch.setattr(
        server,
        "_get_accessible_robot_id",
        lambda args, fallback_robot_id="": fallback_robot_id or "robot-default",
    )

    result = server.call_tool(
        "send_message",
        {
            "text": "critical alert",
            "broadcast": True,
            "_termman_user_id": "user-1",
            "_robot_known_targets": [
                {
                    "conversation": "group:123456",
                    "target_type": "group",
                    "target_id": "123456",
                    "sender": "Alice (10001)",
                    "robot_id": "robot-1",
                },
                {
                    "conversation": "private:654321",
                    "target_type": "private",
                    "target_id": "654321",
                    "sender": "Bob (654321)",
                    "robot_id": "robot-2",
                },
            ],
        },
    )

    assert result == [
        {"type": "text", "text": "Broadcast sent to 2 QQ conversation(s)."}
    ]
    assert sent == [
        ("robot-1", "group", "123456", "critical alert"),
        ("robot-2", "private", "654321", "critical alert"),
    ]


def test_robot_mcp_broadcast_requires_context_target() -> None:
    server = RobotMCPServer()

    result = server.call_tool(
        "send_message",
        {"text": "critical alert", "broadcast": True},
    )

    assert result[0]["type"] == "text"
    assert "broadcast requires at least one visible QQ conversation target" in result[0]["text"]
