import os
import tempfile
import uuid
from pathlib import Path

import pytest

from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.conversation_memory import robot_conversation_memory
from app.services.agent.mcp.robot_context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.mcp.robot_server import RobotMCPServer
from app.services.agent.memory.vector_store import vector_store


@pytest.fixture(autouse=True)
def clear_robot_send_dedupe_cache():
    RobotMCPServer._clear_recent_send_signatures_for_test()
    yield
    RobotMCPServer._clear_recent_send_signatures_for_test()


def _test_memory_dir(name: str) -> Path:
    base = Path(os.environ.get("ROBOT_CONVERSATION_MEMORY_DIR") or tempfile.gettempdir())
    path = base / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_robot_mcp_send_message_requires_context_or_explicit_target() -> None:
    server = RobotMCPServer()

    result = server.call_tool("send_message", {"text": "hello"})

    assert result[0]["type"] == "text"
    assert "no active QQ robot conversation context" in result[0]["text"]
    assert "target_type and target_id" in result[0]["text"]


def test_robot_mcp_send_message_resolves_visible_web_context_target(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: dict[str, object] = {}

    monkeypatch.setattr(
        server,
        "_get_accessible_robot_id",
        lambda args, fallback_robot_id="": fallback_robot_id or "robot-1",
    )

    def fake_send_message(robot_id, reply_target, text):
        sent["robot_id"] = robot_id
        sent["reply_target"] = reply_target
        sent["text"] = text

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    result = server.call_tool(
        "send_message",
        {
            "text": "服务器没开",
            "reply_to": "baka",
            "_robot_known_targets": [
                {
                    "conversation": "group:770362397",
                    "target_type": "group",
                    "target_id": "770362397",
                    "sender": "baka (1874419565)",
                    "robot_id": "robot-1",
                }
            ],
        },
    )

    assert result == [
        {
            "type": "text",
            "text": "Message sent to QQ group 770362397 from chat context.",
        }
    ]
    assert sent["robot_id"] == "robot-1"
    assert sent["text"] == "服务器没开"
    assert isinstance(sent["reply_target"], RobotReplyTarget)
    assert sent["reply_target"].target_type == "group"
    assert sent["reply_target"].target_id == "770362397"


def test_robot_mcp_send_message_noops_no_reply_intent(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: list[str] = []

    def fake_send_message(_robot_id, _reply_target, text):
        sent.append(text)

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    result = server.call_tool(
        "send_message",
        {
            "text": "[no_qq_reply]",
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "No QQ message sent: no reply needed."}
    ]
    assert sent == []


def test_robot_mcp_send_message_suppresses_recent_duplicate(monkeypatch) -> None:
    RobotMCPServer._clear_recent_send_signatures_for_test()
    server = RobotMCPServer()
    target = RobotReplyTarget(
        target_type="group",
        target_id="123456",
        metadata={"target": {"id": "123456"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-current",
            sender_key="onebot_v11:group:123456:user-1",
            reply_target=target,
        )
    )
    sent: list[str] = []

    def fake_send_message(_robot_id, _reply_target, text):
        sent.append(text)

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        first = server.call_tool(
            "send_message",
            {"text": "同一个回复", "_robot_context_token": token},
        )
        second = server.call_tool(
            "send_message",
            {"text": "同一个回复", "_robot_context_token": token},
        )
    finally:
        unregister_robot_mcp_context(token)
        RobotMCPServer._clear_recent_send_signatures_for_test()

    assert first == [
        {"type": "text", "text": "Message sent to current robot conversation."}
    ]
    assert second == [
        {
            "type": "text",
            "text": "Message sent to current robot conversation. Duplicate QQ reply suppressed.",
        }
    ]
    assert sent == ["同一个回复"]


def test_robot_mcp_send_failure_does_not_poison_duplicate_cache(monkeypatch) -> None:
    server = RobotMCPServer()
    target = RobotReplyTarget(
        target_type="group",
        target_id="123456",
        metadata={"target": {"id": "123456"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-current",
            sender_key="onebot_v11:group:123456:user-1",
            reply_target=target,
        )
    )
    attempts = {"count": 0}
    sent: list[str] = []

    def fake_send_message(_robot_id, _reply_target, text):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("bridge down")
        sent.append(text)

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        first = server.call_tool(
            "send_message",
            {"text": "失败后重试", "_robot_context_token": token},
        )
        second = server.call_tool(
            "send_message",
            {"text": "失败后重试", "_robot_context_token": token},
        )
    finally:
        unregister_robot_mcp_context(token)

    assert first[0]["text"] == "Error: bridge down"
    assert second == [
        {"type": "text", "text": "Message sent to current robot conversation."}
    ]
    assert sent == ["失败后重试"]


def test_robot_mcp_send_message_blocks_internal_tool_trace(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: list[str] = []

    def fake_send_message(_robot_id, _reply_target, text):
        sent.append(text)

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    result = server.call_tool(
        "send_message",
        {
            "text": (
                "Executing tool: mcp_robot_send_message\n\n"
                "Message sent to current robot conversation."
            ),
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "No QQ message sent: internal tool trace."}
    ]
    assert sent == []


def test_robot_mcp_send_message_blocks_dsml_tool_trace(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: list[str] = []

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        lambda _robot_id, _reply_target, text: sent.append(text),
    )

    result = server.call_tool(
        "send_message",
        {
            "text": (
                '<｜｜DSML｜｜tool_calls>\n'
                '<｜｜DSML｜｜invoke name="mcp_local_update_task_workflow">\n'
                '<｜｜DSML｜｜parameter name="action" string="true">'
                'complete_current_step</｜｜DSML｜｜parameter>\n'
                '</｜｜DSML｜｜invoke>\n'
                '</｜｜DSML｜｜tool_calls>'
            ),
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "No QQ message sent: internal tool trace."}
    ]
    assert sent == []


def test_robot_mcp_send_message_sanitizes_mixed_internal_trace(
    monkeypatch,
) -> None:
    server = RobotMCPServer()
    sent: list[str] = []
    monkeypatch.setattr(
        robot_conversation_memory,
        "base_dir",
        _test_memory_dir("robot-mcp-send-memory"),
    )

    def fake_send_message(_robot_id, _reply_target, text):
        sent.append(text)

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
            "text": (
                "在呢。需要做什么测试？\n\n"
                "Executing tool: mcp_robot_send_message\n\n"
                "Message sent to current robot conversation.\n\n"
                "[no_qq_reply]"
            ),
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "Message sent to QQ group 123456."}
    ]
    assert sent == ["在呢。需要做什么测试？"]
    memory = robot_conversation_memory.read("robot-2", "group:123456")
    assert "在呢。需要做什么测试？" in memory
    assert "Executing tool" not in memory
    assert "Message sent to current robot conversation" not in memory
    assert "[no_qq_reply]" not in memory


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


def test_robot_mcp_send_message_uses_llm_chosen_messages(monkeypatch) -> None:
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
        lambda args, fallback_robot_id="": "robot-2",
    )

    result = server.call_tool(
        "send_message",
        {
            "messages": ["我先看一下", "等我确认一下状态"],
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "Message sent to QQ group 123456."}
    ]
    assert sent == [
        ("robot-2", "group", "123456", "我先看一下"),
        ("robot-2", "group", "123456", "等我确认一下状态"),
    ]


def test_robot_mcp_send_message_unwraps_structured_text_blocks(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: list[str] = []

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        lambda _robot_id, _reply_target, text: sent.append(text),
    )
    monkeypatch.setattr(
        server,
        "_get_accessible_robot_id",
        lambda args, fallback_robot_id="": "robot-2",
    )

    result = server.call_tool(
        "send_message",
        {
            "messages": [
                {"text": "RCON 也开了，现在可以进游戏了~"},
                {"type": "text", "text": "服务器启动成功啦~ Done (2.901s)！"},
                "{'text': '第三条也是纯文本'}",
            ],
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "Message sent to QQ group 123456."}
    ]
    assert sent == [
        "RCON 也开了，现在可以进游戏了~",
        "服务器启动成功啦~ Done (2.901s)！",
        "第三条也是纯文本",
    ]


def test_robot_mcp_send_message_rejects_long_group_text(monkeypatch) -> None:
    server = RobotMCPServer()
    sent: list[str] = []

    def fake_send_message(_robot_id, _reply_target, text):
        sent.append(text)

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
            "text": "我先看一下这个问题，可能是桥接服务还没接上，也可能是模型没有正确调用发送工具，我确认一下状态",
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result[0]["type"] == "text"
    assert "too long for a single `text` message" in result[0]["text"]
    assert "Use `messages`" in result[0]["text"]
    assert sent == []


def test_robot_mcp_send_message_compacts_paragraphs_inside_each_message(
    monkeypatch,
) -> None:
    server = RobotMCPServer()
    sent: list[str] = []

    def fake_send_message(_robot_id, _reply_target, text):
        sent.append(text)

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
            "messages": ["我先看一下\n\n可能是桥接还没接上", "等我确认一下状态"],
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
        },
    )

    assert result == [
        {"type": "text", "text": "Message sent to QQ group 123456."}
    ]
    assert sent == ["我先看一下可能是桥接还没接上", "等我确认一下状态"]


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


def test_robot_mcp_send_message_allows_visible_context_reply_to_without_active_context(monkeypatch) -> None:
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
        {
            "type": "text",
            "text": "Message sent to QQ group 123456 from chat context.",
        }
    ]
    assert len(sent) == 1
    assert sent[0][0] == "robot-1"
    assert sent[0][1].target_type == "group"
    assert sent[0][1].target_id == "123456"
    assert sent[0][2] == "tell Alice"


def test_robot_mcp_send_message_blocks_only_context_target_without_active_context(
    monkeypatch,
) -> None:
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

    assert result[0]["type"] == "text"
    assert "no active QQ robot conversation context" in result[0]["text"]
    assert sent == []


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


def test_robot_mcp_send_message_blocks_sleeping_active_context(monkeypatch) -> None:
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
            conversation_key="group:current-group",
            conversation_generation=99,
            reply_requires_awake=True,
        )
    )
    sent: list[tuple[str, RobotReplyTarget, str]] = []

    def fake_send_message(robot_id, reply_target, text):
        sent.append((robot_id, reply_target, text))

    monkeypatch.setattr(
        "app.plugins.robot.service.robot_service.conversation_controller_allows_reply",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        result = server.call_tool(
            "send_message",
            {"text": "late reply", "_robot_context_token": token},
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result == [
        {
            "type": "text",
            "text": "Message not sent: current QQ conversation is sleeping or superseded.",
        }
    ]
    assert sent == []

def test_robot_mcp_sleep_conversation_uses_active_context(monkeypatch) -> None:
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
            conversation_key="group:current-group",
            conversation_generation=99,
            reply_requires_awake=True,
        )
    )
    calls: list[tuple[str, str, str]] = []

    def fake_sleep(robot_id, conversation_key, *, reason):
        calls.append((robot_id, conversation_key, reason))
        return True

    monkeypatch.setattr(
        "app.plugins.robot.service.robot_service.sleep_conversation_controller",
        fake_sleep,
    )

    try:
        result = server.call_tool(
            "sleep_conversation",
            {"_robot_context_token": token},
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result == [
        {
            "type": "text",
            "text": "No QQ message sent: current conversation is sleeping.",
        }
    ]
    assert calls == [("robot-current", "group:current-group", "mcp_sleep_conversation")]

def test_robot_mcp_recalls_long_term_memory_scoped_to_active_context(monkeypatch) -> None:
    server = RobotMCPServer()
    calls: list[dict] = []

    def fake_search_memories(**kwargs):
        calls.append(kwargs)
        return [
            {
                "id": "current",
                "content": "nickname is XiaoChai",
                "metadata": {
                    "memory_type": "fact",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:current-group",
                    "verified": True,
                },
                "distance": 0.05,
            },
            {
                "id": "other-group",
                "content": "other group secret",
                "metadata": {
                    "memory_type": "fact",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                },
                "distance": 0.01,
            },
            {
                "id": "same-speaker-other-group",
                "content": "call this QQ user Master",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "speaker_global_key": "onebot_v11:user:user-1",
                    "memory_scope": "speaker",
                },
                "distance": 0.03,
            },
            {
                "id": "other-speaker-other-group",
                "content": "call another user Boss",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "speaker_global_key": "onebot_v11:user:user-2",
                    "memory_scope": "speaker",
                },
                "distance": 0.01,
            },
            {
                "id": "global",
                "content": "general robot preference",
                "metadata": {"memory_type": "preference"},
                "distance": 0.1,
            },
            {
                "id": "other-robot",
                "content": "other robot memory",
                "metadata": {
                    "memory_type": "fact",
                    "robot_id": "robot-other",
                },
                "distance": 0.02,
            },
        ]

    def fake_get_all_memories(item_id, memory_type=None):
        return []

    monkeypatch.setattr(vector_store, "search_memories", fake_search_memories)
    monkeypatch.setattr(vector_store, "get_all_memories", fake_get_all_memories)
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
            conversation_key="group:current-group",
        )
    )

    try:
        result = server.call_tool(
            "recall_memory",
            {
                "_robot_context_token": token,
                "_termman_item_id": "item-1",
                "query": "nickname",
                "n_results": 3,
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert calls[0]["item_id"] == "item-1"
    assert calls[0]["query"] == "nickname"
    assert calls[0]["n_results"] == 18
    text = result[0]["text"]
    assert "nickname is XiaoChai" in text
    assert "call this QQ user Master" in text
    assert "general robot preference" in text
    assert "other group secret" not in text
    assert "call another user Boss" not in text
    assert "other robot memory" not in text
    assert "verified" not in text
    assert "group:current-group" not in text
    assert text.index("nickname is XiaoChai") < text.index("call this QQ user Master")
    assert text.index("call this QQ user Master") < text.index("general robot preference")


def test_robot_mcp_lists_long_term_memory_scoped_to_active_context(monkeypatch) -> None:
    server = RobotMCPServer()
    tools = {tool["name"]: tool for tool in server.list_tools()}
    assert "list_memories" in tools
    assert tools["list_memories"]["skip_memory"] is True

    memories_by_type = {
        "fact": [
            {
                "id": "current-conversation",
                "content": "the bot name is XiaoChai",
                "metadata": {
                    "memory_type": "fact",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:current-group",
                    "memory_scope": "conversation",
                    "speaker": "Alice (user-1)",
                },
            },
            {
                "id": "other-robot",
                "content": "other robot memory",
                "metadata": {
                    "memory_type": "fact",
                    "robot_id": "robot-other",
                },
            },
        ],
        "preference": [
            {
                "id": "same-speaker-other-group",
                "content": "call this QQ user Master",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "speaker_global_key": "onebot_v11:user:user-1",
                    "memory_scope": "speaker",
                },
            },
            {
                "id": "other-speaker",
                "content": "call another QQ user Boss",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "speaker_global_key": "onebot_v11:user:user-2",
                    "memory_scope": "speaker",
                },
            },
        ],
        "context": [
            {
                "id": "other-conversation",
                "content": "other group server port is 19999",
                "metadata": {
                    "memory_type": "context",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "memory_scope": "conversation",
                },
            }
        ],
    }

    def fake_get_all_memories(item_id, memory_type=None):
        assert item_id == "item-1"
        return memories_by_type.get(memory_type, [])

    monkeypatch.setattr(vector_store, "get_all_memories", fake_get_all_memories)
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
            conversation_key="group:current-group",
        )
    )

    try:
        result = server.call_tool(
            "list_memories",
            {
                "_robot_context_token": token,
                "_termman_item_id": "item-1",
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    text = result[0]["text"]
    assert "the bot name is XiaoChai" in text
    assert "call this QQ user Master" in text
    assert "other robot memory" not in text
    assert "call another QQ user Boss" not in text
    assert "other group server port is 19999" not in text
    assert text.index("the bot name is XiaoChai") < text.index("call this QQ user Master")


def test_robot_mcp_list_memories_requires_active_qq_context() -> None:
    server = RobotMCPServer()

    result = server.call_tool(
        "list_memories",
        {"_termman_item_id": "item-1"},
    )

    assert "requires an active QQ robot conversation context" in result[0]["text"]


def test_robot_mcp_recall_uses_scoped_memory_fallback(monkeypatch) -> None:
    server = RobotMCPServer()
    calls: list[tuple[str, str | None]] = []

    def fake_search_memories(**kwargs):
        return [
            {
                "id": "other-vector",
                "content": "other group has a server port",
                "metadata": {
                    "memory_type": "context",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "memory_scope": "conversation",
                },
                "distance": 0.01,
            }
        ]

    scoped_by_type = {
        "context": [
            {
                "id": "current-group-context",
                "content": "current group server port is 28888",
                "metadata": {
                    "memory_type": "context",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:current-group",
                    "memory_scope": "conversation",
                    "verified": True,
                },
            },
            {
                "id": "other-group-context",
                "content": "other group server port is 19999",
                "metadata": {
                    "memory_type": "context",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "memory_scope": "conversation",
                },
            },
        ],
        "preference": [
            {
                "id": "same-speaker-preference",
                "content": "call this QQ user Master",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "speaker_global_key": "onebot_v11:user:user-1",
                    "memory_scope": "speaker",
                },
            },
            {
                "id": "other-speaker-preference",
                "content": "call another QQ user Boss",
                "metadata": {
                    "memory_type": "preference",
                    "robot_id": "robot-current",
                    "robot_conversation_key": "group:other-group",
                    "speaker_global_key": "onebot_v11:user:user-2",
                    "memory_scope": "speaker",
                },
            },
        ],
    }

    def fake_get_all_memories(item_id, memory_type=None):
        calls.append((item_id, memory_type))
        return scoped_by_type.get(memory_type, [])

    monkeypatch.setattr(vector_store, "search_memories", fake_search_memories)
    monkeypatch.setattr(vector_store, "get_all_memories", fake_get_all_memories)
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
            conversation_key="group:current-group",
        )
    )

    try:
        result = server.call_tool(
            "recall_memory",
            {
                "_robot_context_token": token,
                "_termman_item_id": "item-1",
                "query": "server port",
                "n_results": 3,
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert ("item-1", "context") in calls
    assert ("item-1", "preference") in calls
    text = result[0]["text"]
    assert "current group server port is 28888" in text
    assert "call this QQ user Master" in text
    assert "other group has a server port" not in text
    assert "other group server port is 19999" not in text
    assert "call another QQ user Boss" not in text
    assert text.index("current group server port is 28888") < text.index("call this QQ user Master")


def test_robot_mcp_save_memory_persists_scoped_long_term_memory(monkeypatch) -> None:
    server = RobotMCPServer()
    tools = {tool["name"]: tool for tool in server.list_tools()}
    assert "save_memory" in tools
    assert tools["save_memory"]["skip_memory"] is True

    captured: dict[str, object] = {}

    def fake_get_all_memories(item_id: str, memory_type: str | None = None):
        captured["existing_item_id"] = item_id
        captured["existing_memory_type"] = memory_type
        return []

    def fake_add_memory(**kwargs):
        captured.update(kwargs)
        return "memory-123456"

    monkeypatch.setattr(vector_store, "get_all_memories", fake_get_all_memories)
    monkeypatch.setattr(vector_store, "add_memory", fake_add_memory)

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
            conversation_key="group:current-group",
        )
    )

    try:
        result = server.call_tool(
            "save_memory",
            {
                "_robot_context_token": token,
                "_termman_item_id": "item-1",
                "content": "\u4f60\u53eb\u5927\u72d7",
                "memory_type": "fact",
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result[0]["type"] == "text"
    assert "Memory saved" in result[0]["text"]
    assert captured["existing_item_id"] == "item-1"
    assert captured["existing_memory_type"] == "fact"
    assert captured["item_id"] == "item-1"
    assert captured["content"] == "\u4f60\u53eb\u5927\u72d7"
    assert captured["memory_type"] == "fact"
    metadata = captured["metadata"]
    assert metadata["type"] == "robot_agent_saved"
    assert metadata["source"] == "qq_robot_agent"
    assert metadata["verified"] is False
    assert metadata["robot_id"] == "robot-current"
    assert metadata["robot_conversation_key"] == "group:current-group"
    assert metadata["conversation_key"] == "group:current-group"
    assert metadata["speaker_key"] == "onebot_v11:group:current-group:user-1"
    assert metadata["speaker_global_key"] == "onebot_v11:user:user-1"
    assert metadata["memory_scope"] == "robot"
    assert metadata["content_hash"]


def test_robot_mcp_save_memory_does_not_expose_removed_task_type() -> None:
    server = RobotMCPServer()
    save_tool = next(tool for tool in server.list_tools() if tool["name"] == "save_memory")

    assert "task" not in save_tool["inputSchema"]["properties"]["memory_type"]["enum"]


def test_robot_mcp_reads_registered_context_conversation_memory(
    monkeypatch,
    tmp_path,
) -> None:
    server = RobotMCPServer()
    monkeypatch.setattr(robot_conversation_memory, "base_dir", tmp_path)
    robot_conversation_memory.append_user_message(
        "robot-current",
        "group:current-group",
        "hello current keyword",
        sender="Alice (10001)",
    )
    robot_conversation_memory.append_assistant_message(
        "robot-current",
        "group:current-group",
        "assistant current reply",
    )
    robot_conversation_memory.append_user_message(
        "robot-current",
        "group:other-group",
        "other keyword",
        sender="Bob",
    )
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

    try:
        result = server.call_tool(
            "read_conversation_memory",
            {"_robot_context_token": token, "query": "keyword"},
        )
        blocked = server.call_tool(
            "read_conversation_memory",
            {"_robot_context_token": token, "conversation": "group:other-group"},
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result[0]["type"] == "text"
    assert "group:current-group" in result[0]["text"]
    assert "hello current keyword" in result[0]["text"]
    assert "assistant current reply" not in result[0]["text"]
    assert "other keyword" not in result[0]["text"]
    assert "active QQ-triggered context is locked to group:current-group" in blocked[0]["text"]


def test_robot_mcp_read_memory_active_context_caps_requested_lines(
    monkeypatch,
) -> None:
    server = RobotMCPServer()
    monkeypatch.setattr(
        robot_conversation_memory,
        "base_dir",
        _test_memory_dir("robot-mcp-read-memory-cap"),
    )
    robot_conversation_memory.replace(
        "robot-current",
        "group:current-group",
        "".join(
            f"[2026-01-01T00:00:{index:02d}+00:00] user Alice: message-{index:02d}\n"
            for index in range(30)
        ),
    )
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

    try:
        result = server.call_tool(
            "read_conversation_memory",
            {"_robot_context_token": token, "lines": 500},
        )
    finally:
        unregister_robot_mcp_context(token)

    text = result[0]["text"]
    assert "recent 12 line(s)" in text
    assert "message-17" not in text
    assert "message-18" in text
    assert "message-29" in text


def test_robot_mcp_read_memory_sanitizes_old_internal_trace(
    monkeypatch,
) -> None:
    server = RobotMCPServer()
    monkeypatch.setattr(
        robot_conversation_memory,
        "base_dir",
        _test_memory_dir("robot-mcp-read-memory"),
    )
    robot_conversation_memory.replace(
        "robot-current",
        "private:2537134688",
        (
            "[2026-01-01T00:00:00+00:00] user FLY: 测试\n"
            "[2026-01-01T00:00:01+00:00] assistant: 在呢。需要做什么测试？\n"
            "Executing tool: mcp_robot_send_message\n"
            "Message sent to current robot conversation.\n"
            "[no_qq_reply]\n"
        ),
    )
    target = RobotReplyTarget(
        target_type="private",
        target_id="2537134688",
        metadata={"target": {"id": "2537134688", "private": True}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-current",
            sender_key="onebot_v11:private:2537134688",
            reply_target=target,
        )
    )

    try:
        result = server.call_tool(
            "read_conversation_memory",
            {"_robot_context_token": token},
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result[0]["type"] == "text"
    assert "在呢。需要做什么测试？" in result[0]["text"]
    assert "Executing tool" not in result[0]["text"]
    assert "Message sent to current robot conversation" not in result[0]["text"]
    assert "[no_qq_reply]" not in result[0]["text"]


def test_robot_conversation_memory_lists_group_and_private_logs() -> None:
    from app.plugins.robot.conversation_memory import RobotConversationMemoryManager

    manager = RobotConversationMemoryManager(
        base_dir=_test_memory_dir("robot-list-memory")
    )
    manager.replace("robot-1", "group:123456", "[seed] user Alice: hello\n")
    manager.replace("robot-1", "private:654321", "[seed] user Bob: hi\n")

    entries = manager.list_conversations("robot-1")

    assert {entry.conversation_key for entry in entries} == {
        "group:123456",
        "private:654321",
    }
    assert {entry.filename for entry in entries} == {
        "123456.log",
        "private-654321.log",
    }
    assert all(entry.exists for entry in entries)


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


def test_robot_mcp_blocks_reply_to_other_context_from_active_robot_turn(
    monkeypatch,
) -> None:
    server = RobotMCPServer()
    target = RobotReplyTarget(
        target_type="group",
        target_id="current-group",
        metadata={
            "conversation": {
                "type": "group",
                "id": "current-group",
                "target_type": "group",
                "target_id": "current-group",
            }
        },
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-current",
            sender_key="onebot_v11:group:current-group:user-1",
            reply_target=target,
        )
    )
    sent: list[tuple[str, RobotReplyTarget, str]] = []

    def fake_send_message(robot_id, reply_target, text):
        sent.append((robot_id, reply_target, text))

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        result = server.call_tool(
            "send_message",
            {
                "text": "wrong chat",
                "_robot_context_token": token,
                "reply_to": "group:other-group",
                "_robot_known_targets": [
                    {
                        "conversation": "group:other-group",
                        "target_type": "group",
                        "target_id": "other-group",
                        "sender": "Alice (10001)",
                        "robot_id": "robot-current",
                    }
                ],
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result[0]["type"] == "text"
    assert "active QQ-triggered context is locked to group:current-group" in result[0]["text"]
    assert sent == []


def test_robot_mcp_blocks_explicit_other_target_from_active_robot_turn(
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
    sent: list[tuple[str, RobotReplyTarget, str]] = []

    def fake_send_message(robot_id, reply_target, text):
        sent.append((robot_id, reply_target, text))

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        result = server.call_tool(
            "send_message",
            {
                "text": "wrong explicit target",
                "_robot_context_token": token,
                "target_type": "group",
                "target_id": "other-group",
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result[0]["type"] == "text"
    assert "active QQ-triggered context is locked to group:current-group" in result[0]["text"]
    assert sent == []


def test_robot_mcp_blocks_broadcast_from_active_robot_turn(monkeypatch) -> None:
    server = RobotMCPServer()
    target = RobotReplyTarget(
        target_type="private",
        target_id="654321",
        metadata={"target": {"id": "654321", "private": True}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-current",
            sender_key="onebot_v11:private:654321",
            reply_target=target,
        )
    )
    sent: list[tuple[str, RobotReplyTarget, str]] = []

    def fake_send_message(robot_id, reply_target, text):
        sent.append((robot_id, reply_target, text))

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        result = server.call_tool(
            "send_message",
            {
                "text": "broadcast from active",
                "_robot_context_token": token,
                "broadcast": True,
                "_robot_known_targets": [
                    {
                        "conversation": "group:123456",
                        "target_type": "group",
                        "target_id": "123456",
                        "sender": "Alice (10001)",
                        "robot_id": "robot-current",
                    }
                ],
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result[0]["type"] == "text"
    assert "active QQ-triggered context is locked to private:654321" in result[0]["text"]
    assert sent == []


def test_robot_mcp_send_message_blocks_broadcast_without_active_context(monkeypatch) -> None:
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

    assert result[0]["type"] == "text"
    assert "broadcast from prior QQ context is disabled" in result[0]["text"]
    assert sent == []


@pytest.mark.parametrize(
    "partial_target",
    [
        {"target_type": "group"},
        {"target_id": "other-group"},
    ],
)
def test_robot_mcp_ignores_partial_target_in_active_robot_turn(
    monkeypatch,
    partial_target,
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
    sent: list[tuple[str, RobotReplyTarget, str]] = []

    def fake_send_message(robot_id, reply_target, text):
        sent.append((robot_id, reply_target, text))

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )

    try:
        result = server.call_tool(
            "send_message",
            {
                "text": "我是一只猪",
                "_robot_context_token": token,
                **partial_target,
            },
        )
    finally:
        unregister_robot_mcp_context(token)

    assert result == [
        {"type": "text", "text": "Message sent to current robot conversation."}
    ]
    assert len(sent) == 1
    assert sent[0][0] == "robot-current"
    assert sent[0][1].target_id == "current-group"
    assert sent[0][2] == "我是一只猪"


def test_robot_mcp_broadcast_requires_context_target() -> None:
    server = RobotMCPServer()

    result = server.call_tool(
        "send_message",
        {"text": "critical alert", "broadcast": True},
    )

    assert result[0]["type"] == "text"
    assert "broadcast from prior QQ context is disabled" in result[0]["text"]
