from app.plugins.robot.contracts import RobotReplyTarget
from app.services.agent.mcp.robot_context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.mcp.robot_server import RobotMCPServer


def test_robot_mcp_send_message_requires_active_context() -> None:
    server = RobotMCPServer()

    result = server.call_tool("send_message", {"text": "hello"})

    assert result[0]["type"] == "text"
    assert "no active robot conversation context" in result[0]["text"]


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
