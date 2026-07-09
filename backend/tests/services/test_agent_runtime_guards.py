import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.plugins.robot.agent.integration import (
    ROBOT_SEND_TOOL_NAME,
    _should_send_final_response_fallback,
    get_robot_agent_integration,
)
from app.plugins.robot.contracts import RobotInboundMessage, RobotReplyTarget
from app.plugins.robot.conversation_memory import RobotConversationMemoryManager
from app.plugins.robot.prompts import (
    build_robot_delivery_reflection_prompt,
    build_robot_messaging_prompt,
    build_robot_messaging_skill_definition,
)
from app.plugins.robot.reply_intent import is_no_reply_intent
from app.plugins.robot.service import (
    REPLY_MESSAGE_TYPE_GROUP,
    REPLY_MESSAGE_TYPE_MENTION,
    RobotService,
)
from app.services.agent import agent as agent_module
from app.services.agent import chat_runtime
from app.services.agent.agent import AgentContext
from app.services.agent.chat_runtime import (
    ChatResponseResult,
    collect_chat_response,
)
from app.services.agent.mcp.types import MCPTool
from app.services.agent.prompts import builder as prompt_builder
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.skills import skill_loader
from app.services.agent.skills.definition import SkillDefinition
from app.services.log_manager import LogManager


def test_start_mcp_servers_does_not_duplicate_tools(monkeypatch) -> None:
    handler_id = f"handler-{uuid4()}"
    agent = agent_module.Agent(handler_id)
    agent._context = AgentContext(handler_id=handler_id, enabled_mcp_servers=["local"])
    agent._mcp_servers = ["local"]

    tools = [
        MCPTool(
            name="execute_command",
            description="Execute a command",
            input_schema={"type": "object", "properties": {}},
            server_name="local",
        ),
        MCPTool(
            name="read_terminal_log",
            description="Read terminal log",
            input_schema={"type": "object", "properties": {}},
            server_name="local",
        ),
    ]

    monkeypatch.setattr(agent_module.mcp_server_manager, "is_server_running", lambda name: True)
    monkeypatch.setattr(agent_module.mcp_server_manager, "get_tools_for_server", lambda name: tools)

    try:
        asyncio.run(agent.start_mcp_servers())
        asyncio.run(agent.start_mcp_servers())
    finally:
        agent_module.Agent._instances.pop(handler_id, None)

    tool_names = [tool["function"]["name"] for tool in agent.get_tools_for_litellm()]
    assert tool_names == [
        "mcp_local_execute_command",
        "mcp_local_read_terminal_log",
    ]


def test_agent_manager_refreshes_cached_agent_when_skill_revision_changes(monkeypatch) -> None:
    handler_id = f"handler-{uuid4()}"
    handler = SimpleNamespace(
        id=handler_id,
        model="model-a",
        api_key=None,
        api_url=None,
        enabled_skills=["quiet_style"],
        enabled_mcp_servers=[],
        enabled_knowledge_files=[],
        agent_profile={},
    )
    skill = SkillDefinition(skill_id="quiet_style", name="Quiet Style")

    monkeypatch.setattr(agent_module.skill_loader, "get", lambda skill_id: skill)
    monkeypatch.setattr(agent_module.mcp_server_manager, "get_tools_for_server", lambda _name: [])

    manager = agent_module.AgentManager()
    manager._agents.pop(handler_id, None)

    original_revision = agent_module.skill_loader._revision
    try:
        agent_module.skill_loader._revision = 1
        agent = manager.get_or_create(handler)
        assert agent._context.skill_revision == 1

        agent_module.skill_loader._revision = 2
        refreshed = manager.get_or_create(handler)

        assert refreshed is agent
        assert refreshed._context.skill_revision == 2
    finally:
        agent_module.skill_loader._revision = original_revision
        manager._agents.pop(handler_id, None)
        agent_module.Agent._instances.pop(handler_id, None)


def test_robot_context_temporarily_exposes_send_message_tool(monkeypatch) -> None:
    handler_id = f"handler-{uuid4()}"
    agent = agent_module.Agent(handler_id)
    agent._context = AgentContext(handler_id=handler_id, enabled_mcp_servers=[])
    agent._mcp_servers = []

    tools_by_server = {
        "robot": [
            MCPTool(
                name="send_message",
                description="Send robot message",
                input_schema={"type": "object", "properties": {}},
                server_name="robot",
            ),
            MCPTool(
                name="read_conversation_memory",
                description="Read robot conversation memory",
                input_schema={"type": "object", "properties": {}},
                server_name="robot",
            ),
        ]
    }

    monkeypatch.setattr(
        agent_module.mcp_server_manager,
        "is_server_running",
        lambda name: name == "robot",
    )
    monkeypatch.setattr(
        agent_module.mcp_server_manager,
        "get_tools_for_server",
        lambda name: tools_by_server.get(name, []),
    )
    captured_call: dict[str, object] = {}

    async def fake_call_tool(server_name: str, tool_name: str, args: dict):
        captured_call["server_name"] = server_name
        captured_call["tool_name"] = tool_name
        captured_call["args"] = dict(args)
        return [{"type": "text", "text": "sent"}]

    monkeypatch.setattr(
        agent_module.mcp_server_manager,
        "call_tool",
        fake_call_tool,
    )

    try:
        agent.set_robot_context(
            robot_id="robot-1",
            sender_key="onebot_v11:group:g1:u1",
            reply_target=RobotReplyTarget(
                target_type="group",
                target_id="g1",
                metadata={},
            ),
        )
        asyncio.run(agent.ensure_robot_context_tools())

        tool_names = [
            tool["function"]["name"]
            for tool in agent.get_tools_for_litellm()
        ]

        assert agent.get_mcp_servers() == ["robot"]
        assert tool_names == [
            "mcp_robot_send_message",
            "mcp_robot_read_conversation_memory",
        ]

        context_token = agent._context.robot_context_token
        assert "Current robot reply target" in agent._context.robot_reply_context_summary
        assert "conversation: group:g1" in agent._context.robot_reply_context_summary
        assert "sender_key: onebot_v11:group:g1:u1" in (
            agent._context.robot_reply_context_summary
        )

        result = asyncio.run(
            agent.execute_tool("mcp_robot_send_message", {"text": "hello"})
        )

        assert result == {
            "success": True,
            "result": [{"type": "text", "text": "sent"}],
        }
        assert captured_call["server_name"] == "robot"
        assert captured_call["tool_name"] == "send_message"
        assert captured_call["args"] == {
            "text": "hello",
            "_robot_context_token": context_token,
        }

        result = asyncio.run(
            agent.execute_tool(
                "mcp_robot_read_conversation_memory",
                {"query": "hello"},
            )
        )

        assert result == {
            "success": True,
            "result": [{"type": "text", "text": "sent"}],
        }
        assert captured_call["server_name"] == "robot"
        assert captured_call["tool_name"] == "read_conversation_memory"
        assert captured_call["args"] == {
            "query": "hello",
            "_robot_context_token": context_token,
        }

        agent.clear_robot_context()

        assert agent.get_mcp_servers() == []
        assert agent.get_tools_for_litellm() == []
    finally:
        agent.clear_robot_context()
        agent_module.Agent._instances.pop(handler_id, None)


def test_robot_messaging_tools_can_be_temporarily_exposed_for_alerts(monkeypatch) -> None:
    handler_id = f"handler-{uuid4()}"
    agent = agent_module.Agent(handler_id)
    agent._context = AgentContext(handler_id=handler_id, enabled_mcp_servers=[])
    agent._mcp_servers = []

    tools_by_server = {
        "robot": [
            MCPTool(
                name="send_message",
                description="Send robot message",
                input_schema={"type": "object", "properties": {}},
                server_name="robot",
            ),
            MCPTool(
                name="read_conversation_memory",
                description="Read robot conversation memory",
                input_schema={"type": "object", "properties": {}},
                server_name="robot",
            ),
        ]
    }

    monkeypatch.setattr(
        agent_module.mcp_server_manager,
        "is_server_running",
        lambda name: name == "robot",
    )
    monkeypatch.setattr(
        agent_module.mcp_server_manager,
        "get_tools_for_server",
        lambda name: tools_by_server.get(name, []),
    )

    try:
        added = asyncio.run(agent.ensure_robot_messaging_tools())
        tool_names = [
            tool["function"]["name"]
            for tool in agent.get_tools_for_litellm()
        ]

        assert added is True
        assert agent.get_mcp_servers() == ["robot"]
        assert tool_names == [
            "mcp_robot_send_message",
            "mcp_robot_read_conversation_memory",
        ]

        agent.clear_transient_robot_messaging_tools()

        assert agent.get_mcp_servers() == []
        assert agent.get_tools_for_litellm() == []
    finally:
        agent.clear_transient_robot_messaging_tools()
        agent_module.Agent._instances.pop(handler_id, None)


def test_robot_mcp_explicit_target_gets_backend_user_context(monkeypatch) -> None:
    handler_id = f"handler-{uuid4()}"
    agent = agent_module.Agent(handler_id)
    agent._context = AgentContext(
        handler_id=handler_id,
        enabled_mcp_servers=["robot"],
        current_user_id="user-1",
        current_user_is_superuser=False,
    )
    agent._mcp_servers = ["robot"]
    agent._mcp_tools = [
        MCPTool(
            name="send_message",
            description="Send robot message",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_id": {"type": "string"},
                },
            },
            server_name="robot",
        ).to_litellm_tool()
    ]

    captured_call: dict[str, object] = {}

    async def fake_call_tool(server_name: str, tool_name: str, args: dict):
        captured_call["server_name"] = server_name
        captured_call["tool_name"] = tool_name
        captured_call["args"] = dict(args)
        return [{"type": "text", "text": "sent"}]

    monkeypatch.setattr(
        agent_module.mcp_server_manager,
        "call_tool",
        fake_call_tool,
    )

    try:
        result = asyncio.run(
            agent.execute_tool(
                "mcp_robot_send_message",
                {
                    "text": "hello",
                    "target_type": "group",
                    "target_id": "123456",
                    "_termman_user_id": "forged",
                    "_termman_is_superuser": True,
                    "_robot_context_token": "forged-token",
                },
            )
        )

        assert result == {
            "success": True,
            "result": [{"type": "text", "text": "sent"}],
        }
        assert captured_call["server_name"] == "robot"
        assert captured_call["tool_name"] == "send_message"
        assert captured_call["args"] == {
            "text": "hello",
            "target_type": "group",
            "target_id": "123456",
            "_termman_user_id": "user-1",
            "_termman_is_superuser": False,
        }
    finally:
        agent_module.Agent._instances.pop(handler_id, None)


def test_agent_extracts_robot_known_targets_from_context_messages() -> None:
    handler_id = f"handler-{uuid4()}"
    agent = agent_module.Agent(handler_id)
    agent._context = AgentContext(
        handler_id=handler_id,
        enabled_mcp_servers=["robot"],
    )
    agent._context.robot_id = "robot-1"

    try:
        agent.set_robot_known_targets_from_messages(
            [
                {
                    "role": "user",
                    "content": (
                        "[Robot message; conversation=group:123456; "
                        "sender=Alice (10001)]\nserver error"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "[Robot message; conversation=private:654321; "
                        "sender=Bob (654321)]\nhello"
                    ),
                },
            ]
        )

        assert agent._context.robot_known_targets == [
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
        ]
    finally:
        agent_module.Agent._instances.pop(handler_id, None)


def test_robot_context_uses_optional_robot_plugin_prompt(monkeypatch) -> None:
    robot_skill = build_robot_messaging_skill_definition()
    assert robot_skill is not None
    agent = SimpleNamespace(
        _context=SimpleNamespace(robot_id="", robot_reply_context_summary=""),
        get_skills=lambda: [robot_skill],
        get_mcp_servers=lambda: [],
        get_tools_for_litellm=lambda: [],
        match_skills=lambda query: [],
        enabled_knowledge_files=[],
    )
    monkeypatch.setattr(
        prompt_builder,
        "resolve_prompt_memory_policy",
        lambda turn_type: SimpleNamespace(
            include_session_summary=False,
            include_recent_history=True,
            max_recent_messages=4,
            include_long_term=False,
            allowed_long_term_types=(),
            max_long_term_memories=0,
        ),
    )
    monkeypatch.setattr(
        prompt_builder,
        "get_chat_messages",
        lambda item_id: [
            {
                "type": "chat_user",
                "role": "user",
                "content": (
                    "[Robot message; conversation=private:2537134688; "
                    "sender=FLY (2537134688)]\n你好"
                ),
            }
        ],
    )

    messages = prompt_builder.build_chat_turn_messages(
        agent,
        item_id="item-1",
        message="你好",
    )

    assert "QQ MCP Skill" in messages[0]["content"]
    assert "历史中的 QQ 上下文" in messages[0]["content"]
    assert "QQ 回复反思" not in messages[0]["content"]
    assert "mcp_robot_send_message" in messages[0]["content"]




def test_latest_only_chat_prompt_skips_stored_context(monkeypatch) -> None:
    def fail_context_read(*_args, **_kwargs):
        raise AssertionError("stored context should not be read")

    agent = SimpleNamespace(
        _context=SimpleNamespace(robot_id="robot-1", robot_reply_context_summary="current qq"),
        get_skills=lambda: [],
        get_mcp_servers=lambda: [],
        get_tools_for_litellm=lambda: [],
        match_skills=lambda query: [],
        enabled_knowledge_files=["ops.md"],
    )
    monkeypatch.setattr(prompt_builder, "get_system_prompt", lambda agent: "system prompt")
    monkeypatch.setattr(
        prompt_builder,
        "resolve_prompt_memory_policy",
        lambda turn_type: SimpleNamespace(
            include_session_summary=True,
            include_recent_history=True,
            max_recent_messages=10,
            include_long_term=True,
            allowed_long_term_types=("fact", "preference"),
            max_long_term_memories=5,
        ),
    )
    monkeypatch.setattr(prompt_builder, "get_chat_messages", fail_context_read)
    monkeypatch.setattr(prompt_builder, "get_latest_session_summary", fail_context_read)
    monkeypatch.setattr(prompt_builder, "build_integration_history_prompt", fail_context_read)
    monkeypatch.setattr(prompt_builder, "_collect_long_term_memories", fail_context_read)
    monkeypatch.setattr(prompt_builder, "_collect_handler_knowledge", fail_context_read)

    message = (
        "[Robot message; conversation=group:g1; trigger=mention_bot; sender=Bob (u1)]\n"
        "[Current QQ message]\nhello"
    )
    messages = prompt_builder.build_chat_turn_messages(
        agent,
        item_id="item-1",
        message=message,
        latest_only_context=True,
    )

    assert len(messages) == 2
    assert messages[-1] == {"role": "user", "content": message}
    combined = "\n".join(entry["content"] for entry in messages)
    assert "old" not in combined
    assert "Relevant knowledge files" not in combined

def test_non_robot_context_does_not_include_robot_plugin_prompt(monkeypatch) -> None:
    agent = SimpleNamespace(
        _context=SimpleNamespace(robot_id="", robot_reply_context_summary=""),
        get_skills=lambda: [],
        get_mcp_servers=lambda: [],
        get_tools_for_litellm=lambda: [],
        match_skills=lambda query: [],
        enabled_knowledge_files=[],
    )
    monkeypatch.setattr(
        prompt_builder,
        "resolve_prompt_memory_policy",
        lambda turn_type: SimpleNamespace(
            include_session_summary=False,
            include_recent_history=True,
            max_recent_messages=4,
            include_long_term=False,
            allowed_long_term_types=(),
            max_long_term_memories=0,
        ),
    )
    monkeypatch.setattr(prompt_builder, "get_chat_messages", lambda item_id: [])

    messages = prompt_builder.build_chat_turn_messages(
        agent,
        item_id="item-1",
        message="hello",
    )

    assert "QQ MCP Skill" not in messages[0]["content"]
    assert "mcp_robot_send_message" not in messages[0]["content"]


def test_robot_history_context_does_not_inject_prompt_without_robot_skill(monkeypatch) -> None:
    agent = SimpleNamespace(
        _context=SimpleNamespace(robot_id="", robot_reply_context_summary=""),
        get_skills=lambda: [],
        get_mcp_servers=lambda: [],
        get_tools_for_litellm=lambda: [],
        match_skills=lambda query: [],
        enabled_knowledge_files=[],
    )
    monkeypatch.setattr(
        prompt_builder,
        "resolve_prompt_memory_policy",
        lambda turn_type: SimpleNamespace(
            include_session_summary=False,
            include_recent_history=True,
            max_recent_messages=4,
            include_long_term=False,
            allowed_long_term_types=(),
            max_long_term_memories=0,
        ),
    )
    monkeypatch.setattr(
        prompt_builder,
        "get_chat_messages",
        lambda item_id: [
            {
                "type": "chat_user",
                "role": "user",
                "content": "[Robot message; conversation=group:g1; sender=Alice]\nhello",
            }
        ],
    )

    messages = prompt_builder.build_chat_turn_messages(
        agent,
        item_id="item-1",
        message="hello",
    )

    assert "QQ MCP Skill" not in messages[0]["content"]
    assert "mcp_robot_send_message" not in messages[0]["content"]


def test_critical_terminal_prompt_forces_alert_skill(monkeypatch) -> None:
    critical_skill = SimpleNamespace(
        skill_id="terminal_mcp",
        name="终端 MCP",
        description="终端 MCP 能力",
        category="mcp",
        action=SimpleNamespace(prompt="terminal mcp prompt body"),
        content="",
    )
    agent = SimpleNamespace(
        get_skills=lambda: [critical_skill],
        match_skills=lambda query: [],
        enabled_knowledge_files=[],
    )
    monkeypatch.setattr(
        prompt_builder,
        "resolve_prompt_memory_policy",
        lambda turn_type: SimpleNamespace(
            include_session_summary=False,
            max_recent_messages=0,
            include_recent_history=False,
            include_long_term=False,
            allowed_long_term_types=(),
            max_long_term_memories=0,
        ),
    )

    critical_messages = prompt_builder.build_terminal_turn_messages(
        agent,
        item_id="item-1",
        terminal_content="FATAL: service crashed and exited with code 1",
    )
    normal_messages = prompt_builder.build_terminal_turn_messages(
        agent,
        item_id="item-1",
        terminal_content="error: file not found during investigation",
    )

    assert "terminal mcp prompt body" in critical_messages[0]["content"]
    assert "terminal mcp prompt body" not in normal_messages[0]["content"]


def test_robot_delivery_retry_triggers_when_model_returns_plain_reply() -> None:
    tools = [
        {
            "type": "function",
            "function": {"name": ROBOT_SEND_TOOL_NAME},
        }
    ]
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_known_targets=[
                {
                    "conversation": "private:2537134688",
                    "target_type": "private",
                    "target_id": "2537134688",
                    "sender": "FLY (2537134688)",
                }
            ],
        )
    )
    messages = [
        {
            "role": "user",
            "content": (
                "[Robot message; conversation=private:2537134688; "
                "sender=FLY (2537134688)]\n你好"
            ),
        }
    ]
    integration = get_robot_agent_integration()

    assert integration.should_retry_delivery(
        agent=agent,
        messages=messages,
        tools=tools,
        final_response="你好呀~",
        retry_used=False,
    ) is True
    assert integration.should_retry_delivery(
        agent=agent,
        messages=messages,
        tools=tools,
        final_response="你好呀~",
        retry_used=True,
    ) is False

    correction = integration.delivery_correction_message("你好呀~")
    assert correction["role"] == "system"
    assert "QQ 消息发送反思" in correction["content"]
    assert "重新判断 QQ 是否应该收到这段文本" in correction["content"]
    assert "mcp_robot_send_message" in correction["content"]
    assert "你好呀~" in correction["content"]


def test_robot_collect_response_fallback_accepts_mcp_tool_delivery() -> None:
    assert get_robot_agent_integration().fallback_response_content(
        {"robot_id": "robot-1"},
        tool_results=["Message sent to QQ group 123456 from chat context."],
        warnings=[],
        done_seen=True,
    ) == "Message sent to QQ group 123456 from chat context."


def test_robot_delivery_retry_skips_no_reply_intent() -> None:
    tools = [{"type": "function", "function": {"name": ROBOT_SEND_TOOL_NAME}}]
    agent = SimpleNamespace(
        _context=SimpleNamespace(robot_id="robot-1", robot_known_targets=[])
    )
    messages = [
        {
            "role": "user",
            "content": "[Robot message; conversation=group:123456]\nhello",
        }
    ]

    assert is_no_reply_intent("[no_qq_reply]")
    assert get_robot_agent_integration().should_retry_delivery(
        agent=agent,
        messages=messages,
        tools=tools,
        final_response="[no_qq_reply]",
        retry_used=False,
    ) is False


def test_robot_plain_reply_bridge_fallback_requires_direct_wakeup() -> None:
    direct_target = RobotReplyTarget(
        target_type="group",
        target_id="123456",
        metadata={"mentioned_bot": True},
    )
    passive_target = RobotReplyTarget(
        target_type="group",
        target_id="123456",
        metadata={},
    )

    assert _should_send_final_response_fallback(
        robot_id="robot-1",
        robot_reply_target=direct_target,
        content="pong",
        robot_message_sent=False,
    )
    assert not _should_send_final_response_fallback(
        robot_id="robot-1",
        robot_reply_target=passive_target,
        content="pong",
        robot_message_sent=False,
    )
    assert _should_send_final_response_fallback(
        robot_id="robot-1",
        robot_reply_target=passive_target,
        content="pong",
        robot_message_sent=False,
        reply_requires_awake=True,
    )
    assert not _should_send_final_response_fallback(
        robot_id=None,
        robot_reply_target=direct_target,
        content="pong",
        robot_message_sent=False,
    )
    assert not _should_send_final_response_fallback(
        robot_id="robot-1",
        robot_reply_target=direct_target,
        content="",
        robot_message_sent=False,
    )
    assert not _should_send_final_response_fallback(
        robot_id="robot-1",
        robot_reply_target=direct_target,
        content="pong",
        robot_message_sent=True,
    )


def test_robot_plain_reply_bridge_fallback_skips_no_reply_intent(monkeypatch) -> None:
    sent: list[str] = []

    def fake_send_message(_robot_id, _target, text) -> None:
        sent.append(text)

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    reply_target = RobotReplyTarget(
        target_type="group",
        target_id="123456",
        metadata={"mentioned_bot": True},
    )

    delivered = get_robot_agent_integration().send_final_response_fallback(
        {
            "robot_id": "robot-1",
            "reply_target": reply_target,
        },
        content="[no_qq_reply]",
        message_sent=False,
    )

    assert delivered is False
    assert sent == []


def test_robot_plain_reply_bridge_fallback_sends_active_window_reply(monkeypatch) -> None:
    sent: dict[str, object] = {}
    allowed_calls: list[tuple[str, str, int, bool]] = []

    def fake_send_message(robot_id, target, text) -> None:
        sent["robot_id"] = robot_id
        sent["target"] = target
        sent["text"] = text

    def fake_allows_reply(robot_id, conversation_key, generation, *, requires_awake):
        allowed_calls.append((robot_id, conversation_key, generation, requires_awake))
        return True

    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    monkeypatch.setattr(
        "app.plugins.robot.service.robot_service.conversation_controller_allows_reply",
        fake_allows_reply,
    )
    monkeypatch.setattr(
        "app.plugins.robot.conversation_memory.robot_conversation_memory.append_assistant_message",
        lambda *_args, **_kwargs: None,
    )

    reply_target = RobotReplyTarget(
        target_type="group",
        target_id="123456",
        metadata={"target": {"id": "123456"}},
    )

    delivered = get_robot_agent_integration().send_final_response_fallback(
        {
            "robot_id": "robot-1",
            "sender_key": "onebot_v11:group:123456:u1",
            "reply_target": reply_target,
            "conversation_key": "group:123456",
            "conversation_generation": 7,
            "reply_requires_awake": True,
        },
        content="pong",
        message_sent=False,
    )

    assert delivered is True
    assert sent == {
        "robot_id": "robot-1",
        "target": reply_target,
        "text": "pong",
    }
    assert allowed_calls == [("robot-1", "group:123456", 7, True)]

def test_robot_collect_response_sends_plain_final_reply_for_direct_mention(
    monkeypatch,
) -> None:
    class FakeAgent:
        def __init__(self) -> None:
            self.context_set = False
            self.tools_requested = False
            self.context_cleared = False

        def setup_context(self, agent, context: dict) -> None:
            self.context_set = True
            self.robot_context = dict(context)

        async def ensure_tools(self, agent, context: dict) -> None:
            self.tools_requested = True

        def clear_context(self, agent, context: dict) -> None:
            self.context_cleared = True

    fake_agent = FakeAgent()

    async def fake_prepare_chat_agent(*_args, **_kwargs):
        return SimpleNamespace(name="handler"), SimpleNamespace(id="item-1"), fake_agent

    def fake_generate_stream(**_kwargs):
        yield 'data: {"type": "agent_response", "content": "pong"}\n\n'
        yield 'data: {"done": true}\n\n'

    sent: dict[str, object] = {}

    def fake_send_message(robot_id, target, text) -> None:
        sent["robot_id"] = robot_id
        sent["target"] = target
        sent["text"] = text

    monkeypatch.setattr(chat_runtime, "prepare_chat_agent", fake_prepare_chat_agent)
    monkeypatch.setattr("app.api.routes.chat.generate_stream", fake_generate_stream)
    integration = get_robot_agent_integration()
    monkeypatch.setattr(integration, "setup_chat_context", fake_agent.setup_context)
    monkeypatch.setattr(integration, "ensure_chat_context_tools", fake_agent.ensure_tools)
    monkeypatch.setattr(integration, "clear_chat_context", fake_agent.clear_context)
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integration",
        lambda name: integration if name == "robot" else None,
    )
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integrations",
        lambda: [integration],
    )
    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        fake_send_message,
    )
    reply_target = RobotReplyTarget(
        target_type="group",
        target_id="123456",
        metadata={"mentioned_bot": True},
    )

    result = asyncio.run(
        collect_chat_response(
            session=SimpleNamespace(),
            item_id="item-1",
            current_user=SimpleNamespace(),
            message="say something",
            robot_id="robot-1",
            robot_sender_key="onebot_v11:group:123456:u1",
            robot_reply_target=reply_target,
            return_result=True,
        )
    )

    assert isinstance(result, ChatResponseResult)
    assert result.content == "pong"
    assert result.robot_message_sent is True
    assert fake_agent.context_set is True
    assert fake_agent.tools_requested is True
    assert fake_agent.context_cleared is True
    assert sent == {
        "robot_id": "robot-1",
        "target": reply_target,
        "text": "pong",
    }


def test_robot_collect_response_does_not_return_send_tool_trace(
    monkeypatch,
) -> None:
    class FakeAgent:
        def setup_context(self, agent, context: dict) -> None:
            return None

        async def ensure_tools(self, agent, context: dict) -> None:
            return None

        def clear_context(self, agent, context: dict) -> None:
            return None

    async def fake_prepare_chat_agent(*_args, **_kwargs):
        return SimpleNamespace(name="handler"), SimpleNamespace(id="item-1"), FakeAgent()

    def fake_generate_stream(**_kwargs):
        yield (
            'data: {"type": "agent_response", '
            '"content": "Executing tool: mcp_robot_send_message"}\n\n'
        )
        yield (
            'data: {"type": "agent_tool_result", '
            '"content": "Message sent to current robot conversation."}\n\n'
        )
        yield 'data: {"done": true}\n\n'

    monkeypatch.setattr(chat_runtime, "prepare_chat_agent", fake_prepare_chat_agent)
    monkeypatch.setattr("app.api.routes.chat.generate_stream", fake_generate_stream)
    sent: list[str] = []
    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        lambda _robot_id, _target, text: sent.append(text),
    )
    integration = get_robot_agent_integration()
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integration",
        lambda name: integration if name == "robot" else None,
    )
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integrations",
        lambda: [integration],
    )

    result = asyncio.run(
        collect_chat_response(
            session=SimpleNamespace(),
            item_id="item-1",
            current_user=SimpleNamespace(),
            message="say something",
            robot_id="robot-1",
            robot_sender_key="onebot_v11:group:123456:u1",
            robot_reply_target=RobotReplyTarget(
                target_type="group",
                target_id="123456",
                metadata={"mentioned_bot": True},
            ),
            return_result=True,
        )
    )

    assert isinstance(result, ChatResponseResult)
    assert result.content == ""
    assert result.robot_message_sent is True


def test_robot_collect_response_suppresses_final_after_send_tool_result(
    monkeypatch,
) -> None:
    class FakeAgent:
        def setup_context(self, agent, context: dict) -> None:
            return None

        async def ensure_tools(self, agent, context: dict) -> None:
            return None

        def clear_context(self, agent, context: dict) -> None:
            return None

    async def fake_prepare_chat_agent(*_args, **_kwargs):
        return SimpleNamespace(name="handler"), SimpleNamespace(id="item-1"), FakeAgent()

    def fake_generate_stream(**_kwargs):
        yield (
            'data: {"type": "agent_tool_result", '
            '"content": "Message sent to current robot conversation."}\n\n'
        )
        yield (
            'data: {"type": "agent_response", '
            '"content": "联网查到啦～现在是北京时间 2026年7月3日 周五 上午 11:17"}\n\n'
        )
        yield 'data: {"done": true}\n\n'

    monkeypatch.setattr(chat_runtime, "prepare_chat_agent", fake_prepare_chat_agent)
    monkeypatch.setattr("app.api.routes.chat.generate_stream", fake_generate_stream)
    sent: list[str] = []
    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        lambda _robot_id, _target, text: sent.append(text),
    )
    integration = get_robot_agent_integration()
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integration",
        lambda name: integration if name == "robot" else None,
    )
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integrations",
        lambda: [integration],
    )

    result = asyncio.run(
        collect_chat_response(
            session=SimpleNamespace(),
            item_id="item-1",
            current_user=SimpleNamespace(),
            message="现在几点",
            robot_id="robot-1",
            robot_sender_key="onebot_v11:group:123456:u1",
            robot_reply_target=RobotReplyTarget(
                target_type="group",
                target_id="123456",
                metadata={"mentioned_bot": True},
            ),
            return_result=True,
        )
    )

    assert isinstance(result, ChatResponseResult)
    assert result.content == ""
    assert result.robot_message_sent is True
    assert sent == []


def test_robot_collect_response_sanitizes_mixed_send_tool_trace(
    monkeypatch,
) -> None:
    class FakeAgent:
        def setup_context(self, agent, context: dict) -> None:
            return None

        async def ensure_tools(self, agent, context: dict) -> None:
            return None

        def clear_context(self, agent, context: dict) -> None:
            return None

    async def fake_prepare_chat_agent(*_args, **_kwargs):
        return SimpleNamespace(name="handler"), SimpleNamespace(id="item-1"), FakeAgent()

    def fake_generate_stream(**_kwargs):
        yield (
            'data: {"type": "agent_response", '
            '"content": "在呢。需要做什么测试？\\n\\nExecuting tool: '
            'mcp_robot_send_message\\n\\nMessage sent to current robot conversation.'
            '\\n\\n[no_qq_reply]"}\n\n'
        )
        yield 'data: {"done": true}\n\n'

    monkeypatch.setattr(chat_runtime, "prepare_chat_agent", fake_prepare_chat_agent)
    monkeypatch.setattr("app.api.routes.chat.generate_stream", fake_generate_stream)
    sent: list[str] = []
    monkeypatch.setattr(
        "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
        lambda _robot_id, _target, text: sent.append(text),
    )
    integration = get_robot_agent_integration()
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integration",
        lambda name: integration if name == "robot" else None,
    )
    monkeypatch.setattr(
        "app.services.agent.integrations.hooks.get_agent_integrations",
        lambda: [integration],
    )

    result = asyncio.run(
        collect_chat_response(
            session=SimpleNamespace(),
            item_id="item-1",
            current_user=SimpleNamespace(),
            message="测试",
            robot_id="robot-1",
            robot_sender_key="onebot_v11:private:2537134688",
            robot_reply_target=RobotReplyTarget(
                target_type="private",
                target_id="2537134688",
                metadata={"mentioned_bot": True},
            ),
            return_result=True,
        )
    )

    assert isinstance(result, ChatResponseResult)
    assert result.content == "在呢。需要做什么测试？"
    assert result.robot_message_sent is True
    assert sent == ["在呢。需要做什么测试？"]


def test_robot_collect_response_fallback_accepts_warning_completion() -> None:
    assert get_robot_agent_integration().fallback_response_content(
        {"robot_id": "robot-1"},
        tool_results=[],
        warnings=["Stopped after reaching the max iteration limit (10)"],
        done_seen=True,
    ) == "Stopped after reaching the max iteration limit (10)"


def test_non_robot_collect_response_still_requires_content() -> None:
    assert (
        get_robot_agent_integration().fallback_response_content(
            {"robot_id": None},
            tool_results=["Message sent to QQ group 123456."],
            warnings=["warning"],
            done_seen=True,
        )
        == ""
    )


def test_robot_context_system_prompt_uses_robot_plugin_prompt() -> None:
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.plugins.robot.mcp.context import build_robot_reply_context_summary

    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_reply_context_summary=build_robot_reply_context_summary(
                RobotReplyTarget(
                    target_type="group",
                    target_id="g1",
                    metadata={
                        "conversation": {"type": "group", "id": "g1"},
                        "sender": {
                            "display_name": "Alice",
                            "user_id": "u1",
                        },
                    },
                ),
                "onebot_v11:group:g1:u1",
            ),
        ),
        get_skills=lambda: [],
    )

    prompt = get_system_prompt(agent)

    assert "QQ MCP Skill" in prompt
    assert "Current robot reply target" in prompt
    assert "conversation: group:g1" in prompt
    assert "sender: Alice (u1)" in prompt
    assert "最终 assistant 文本是 TermMan 内部回复" in prompt
    assert "mcp_robot_send_message" in prompt
    assert "mcp_robot_save_memory" in prompt
    assert "mcp_robot_sleep_conversation" in prompt
    assert "trigger=active_chat_window" in prompt
    assert "当前 QQ 会话" in prompt
    assert "只调用 `mcp_robot_send_message` 并只传 `text` 或 `messages`" in prompt
    assert "不要在单条 QQ 消息里写空行" in prompt
    assert "QQ 回复反思" not in prompt


def test_robot_plugin_prompt_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr("app.plugins.robot.prompts.is_robot_plugin_enabled", lambda: False)

    assert build_robot_messaging_prompt() == ""
    assert build_robot_delivery_reflection_prompt("hello") == ""


def test_robot_plugin_registers_builtin_skill() -> None:
    skill = skill_loader.get("qq_mcp")

    assert skill is not None
    assert skill.category == "mcp"
    assert skill.mcp_servers == ["robot"]
    assert "mcp_robot_send_message" in (skill.action.prompt or "")
    assert "mcp_robot_save_memory" in (skill.action.prompt or "")


def test_builtin_skills_are_terminal_qq_mcp_and_personas() -> None:
    terminal_mcp = skill_loader.get("terminal_mcp")
    qq_mcp = skill_loader.get("qq_mcp")
    mutsumi = skill_loader.get("mutsumi_persona")
    kurumi = skill_loader.get("tokisaki_kurumi_persona")
    yui = skill_loader.get("hirasawa_yui_persona")

    assert terminal_mcp is not None
    assert qq_mcp is not None
    assert mutsumi is not None
    assert kurumi is not None
    assert yui is not None
    assert terminal_mcp.category == "mcp"
    assert qq_mcp.category == "mcp"
    assert mutsumi.skill_dir == "mutsumi_persona"
    assert kurumi.skill_dir == "tokisaki_kurumi_persona"
    assert yui.skill_dir == "hirasawa_yui_persona"
    assert mutsumi.category == "persona"
    assert kurumi.category == "persona"
    assert yui.category == "persona"
    assert "终端 MCP Skill" in (terminal_mcp.action.prompt or "")
    assert "mcp_local_record_installed_software" in (terminal_mcp.action.prompt or "")
    assert "mcp_local_remove_installed_software" in (terminal_mcp.action.prompt or "")
    assert "不要拼接 shell 命令" in (terminal_mcp.action.prompt or "")
    assert "`&&`" in (terminal_mcp.action.prompt or "")
    assert "QQ MCP Skill" in (qq_mcp.action.prompt or "")
    assert "若叶睦人格 Skill" in (mutsumi.action.prompt or "")
    assert "时崎狂三人格 Skill" in (kurumi.action.prompt or "")
    assert "平泽唯人格 Skill" in (yui.action.prompt or "")
    assert "有语气、有停顿，但别嘴碎" in (mutsumi.action.prompt or "")
    assert "有语气、有停顿，但别嘴碎" in (kurumi.action.prompt or "")
    assert "有语气、有停顿，但别嘴碎" in (yui.action.prompt or "")
    assert "不要拆成电报式碎片" in (mutsumi.action.prompt or "")
    assert "不要拆成电报式碎片" in (kurumi.action.prompt or "")
    assert "不要拆成电报式碎片" in (yui.action.prompt or "")
    assert "群聊单条 text 不要超过 36 个字" in (mutsumi.action.prompt or "")
    assert "群聊单条 text 不要超过 36 个字" in (kurumi.action.prompt or "")
    assert "群聊单条 text 不要超过 36 个字" in (yui.action.prompt or "")
    assert "不要在单条 QQ 消息里写空行" in (mutsumi.action.prompt or "")
    assert "不要在单条 QQ 消息里写空行" in (kurumi.action.prompt or "")
    assert "不要在单条 QQ 消息里写空行" in (yui.action.prompt or "")
    assert "最多 3 条" in (mutsumi.action.prompt or "")
    assert "最多 3 条" in (kurumi.action.prompt or "")
    assert "最多 3 条" in (yui.action.prompt or "")
    assert "不要把一整段长话交给后端拆" in (mutsumi.action.prompt or "")
    assert "不要把一整段长话交给后端拆" in (kurumi.action.prompt or "")
    assert "不要把一整段长话交给后端拆" in (yui.action.prompt or "")
    assert "不要为了分次回而重复调用发送工具" in (mutsumi.action.prompt or "")
    assert "不要为了分次回而重复调用发送工具" in (kurumi.action.prompt or "")
    assert "不要为了分次回而重复调用发送工具" in (yui.action.prompt or "")
    assert "尽量不要句号" in (mutsumi.action.prompt or "")
    assert "尽量不要句号" in (kurumi.action.prompt or "")
    assert "尽量不要句号" in (yui.action.prompt or "")
    persona_no_emoji_rule = "不要使用 emoji"
    assert persona_no_emoji_rule in (mutsumi.action.prompt or "")
    assert persona_no_emoji_rule in (kurumi.action.prompt or "")
    assert persona_no_emoji_rule in (yui.action.prompt or "")



def test_robot_plain_group_message_is_group_category_not_mention() -> None:
    service = RobotService()
    message = RobotInboundMessage(
        sender_key="onebot_v11:group:770362397:user:10001",
        text="ordinary chatter",
        reply_target=RobotReplyTarget(
            target_type="group",
            target_id="770362397",
            metadata={
                "conversation": {"type": "group", "id": "770362397"},
                "target": {"message_type": "group", "group_id": "770362397"},
            },
        ),
    )
    command = service._parse_robot_command(message.text)

    categories = service._reply_message_categories(message, command)

    assert REPLY_MESSAGE_TYPE_GROUP in categories
    assert REPLY_MESSAGE_TYPE_MENTION not in categories


def test_robot_empty_direct_wakeup_is_group_and_mention_category() -> None:
    service = RobotService()
    message = RobotInboundMessage(
        sender_key="onebot_v11:group:770362397:user:10001",
        text="",
        reply_target=RobotReplyTarget(
            target_type="group",
            target_id="770362397",
            metadata={
                "mentioned_bot": True,
                "conversation": {"type": "group", "id": "770362397"},
                "target": {"message_type": "group", "group_id": "770362397"},
            },
        ),
    )
    command = service._parse_robot_command("[empty robot wakeup]")

    categories = service._reply_message_categories(
        message,
        command,
        direct_reply_trigger=service._message_directly_addresses_bot(message),
    )

    assert REPLY_MESSAGE_TYPE_GROUP in categories
    assert REPLY_MESSAGE_TYPE_MENTION in categories


def test_robot_conversation_memory_prompt_defaults_to_latest_entries(tmp_path: Path) -> None:
    manager = RobotConversationMemoryManager(base_dir=tmp_path, max_bytes=4096)
    for index in range(12):
        manager.append_user_message(
            "robot-1",
            "group:770362397",
            f"message-{index:02d}",
            sender="Alice",
        )

    prompt = manager.format_prompt_memory("robot-1", "group:770362397")

    assert "latest 8 entries only" in prompt
    assert "message-03" not in prompt
    assert "message-04" in prompt
    assert "message-11" in prompt
    assert "not new messages waiting for a reply" in prompt

def test_log_manager_reads_legacy_log_when_primary_missing(tmp_path) -> None:
    primary_dir = tmp_path / ".runtime" / "item_logs"
    legacy_dir = tmp_path / "backend" / "app" / "services" / "log"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    manager = LogManager(base_dir=str(primary_dir))
    manager._legacy_base_dir = legacy_dir
    item_id = "item-1"

    legacy_path = legacy_dir / f"{item_id}.log"
    legacy_path.write_text("legacy line\n", encoding="utf-8")

    assert Path(manager.base_dir) == primary_dir.resolve()
    assert manager.get_log_content("user-1", item_id) == "legacy line\n"
    assert manager.get_last_lines(item_id, lines=1) == "legacy line\n"
    assert manager.get_line_count(item_id) == 1
    assert manager.get_lines_since(item_id, start_line=0) == "legacy line\n"

    assert manager.write_to_log("user-1", item_id, "primary line\n") is True
    assert manager.get_last_lines(item_id, lines=1) == "primary line\n"


def test_robot_conversation_memory_uses_group_log_and_prompt(tmp_path: Path) -> None:
    manager = RobotConversationMemoryManager(base_dir=tmp_path, max_bytes=4096)
    info = manager.append_user_message(
        "robot-1",
        "group:770362397",
        "说话",
        sender="Alice (10001)",
    )
    manager.append_assistant_message("robot-1", "group:770362397", "在")
    manager.append_user_message("robot-1", "group:other", "别的群", sender="Bob")

    assert info.path.endswith("770362397.log")
    assert "说话" in manager.read("robot-1", "group:770362397")
    assert "别的群" not in manager.read("robot-1", "group:770362397")

    prompt = manager.format_prompt_memory("robot-1", "group:770362397")
    assert "Current QQ conversation .log memory" in prompt
    assert "group:770362397" in prompt
    assert "Alice (10001)" in prompt
    assert "说话" in prompt
    assert "别的群" not in prompt


def test_turn_guard_allows_multiple_distinct_terminal_log_reads() -> None:
    from app.services.agent.session import READ_LOG_TOOL_NAME, TurnGuard

    guard = TurnGuard()

    for index in range(5):
        stopped, reason = guard.before_tool(READ_LOG_TOOL_NAME, "{}")
        assert stopped is False
        assert reason == ""

        stopped, reason = guard.after_tool(READ_LOG_TOOL_NAME, f"log content {index}")
        assert stopped is False
        assert reason == ""


def test_turn_guard_stops_repeated_unchanged_terminal_log_reads() -> None:
    from app.services.agent.session import READ_LOG_TOOL_NAME, TurnGuard

    guard = TurnGuard()

    for _ in range(2):
        stopped, reason = guard.before_tool(READ_LOG_TOOL_NAME, "{}")
        assert stopped is False
        assert reason == ""

        stopped, reason = guard.after_tool(READ_LOG_TOOL_NAME, "same log content")
        assert stopped is False
        assert reason == ""

    stopped, reason = guard.before_tool(READ_LOG_TOOL_NAME, "{}")
    assert stopped is False
    assert reason == ""

    stopped, reason = guard.after_tool(READ_LOG_TOOL_NAME, "same log content")
    assert stopped is True
    assert reason


def test_command_dispatch_failure_result_detects_terminal_failure() -> None:
    from app.services.agent.session import (
        COMMAND_DISPATCH_FAILURE_MESSAGE,
        is_command_dispatch_failure_result,
    )

    assert is_command_dispatch_failure_result(
        "mcp_local_execute_command",
        COMMAND_DISPATCH_FAILURE_MESSAGE,
    )
    assert is_command_dispatch_failure_result(
        "mcp_local_interrupt_command",
        "终端未收到命令",
    )
    assert not is_command_dispatch_failure_result(
        "mcp_local_read_terminal_log",
        COMMAND_DISPATCH_FAILURE_MESSAGE,
    )
    assert not is_command_dispatch_failure_result(
        "mcp_local_execute_command",
        "命令已发送到终端，尚未确认执行结果: java -version",
    )


def test_terminal_input_mode_classifies_busy_and_console_commands() -> None:
    from app.services.agent.session import (
        TERMINAL_INPUT_MODE_BUSY,
        TERMINAL_INPUT_MODE_CONSOLE,
        classify_terminal_input_mode,
        is_terminal_console_command,
    )

    assert classify_terminal_input_mode("apt update") == TERMINAL_INPUT_MODE_BUSY
    assert classify_terminal_input_mode("pip install fastapi") == TERMINAL_INPUT_MODE_BUSY
    assert classify_terminal_input_mode("npm install") == TERMINAL_INPUT_MODE_BUSY
    assert classify_terminal_input_mode("java -jar paper-server.jar nogui") == TERMINAL_INPUT_MODE_CONSOLE
    assert classify_terminal_input_mode("java -version") is None
    assert is_terminal_console_command("op Steve") is True
    assert is_terminal_console_command("/say hello") is True
    assert is_terminal_console_command("ls -la") is False
    assert is_terminal_console_command("op Steve && ls") is False


def test_busy_pending_terminal_command_blocks_new_shell_input() -> None:
    from app.services.agent.session import AgentSession, EXECUTE_COMMAND_TOOL_NAME

    session = AgentSession("item-1", "handler-1")
    session._schedule_pending_command_recheck = lambda *args, **kwargs: None
    session._get_log_line_count = lambda: 0

    session._set_pending_command(EXECUTE_COMMAND_TOOL_NAME, {"command": "apt update"})

    assert session._get_pending_command() is not None
    warning = session._validate_terminal_command_input(
        EXECUTE_COMMAND_TOOL_NAME,
        {"command": "ls -la"},
    )

    assert warning is not None
    assert "apt update" in warning
    assert "ls -la" in warning

    should_hold, resolved, direct = session._maybe_hold_for_pending_terminal_feedback(
        "[2026-07-08 10:00:00] Get:1 http://example.test stable InRelease"
    )

    assert (should_hold, resolved, direct) == (False, None, False)
    assert session._get_pending_command() is not None


def test_console_terminal_context_allows_console_input_but_blocks_shell_input() -> None:
    from app.services.agent.session import AgentSession, EXECUTE_COMMAND_TOOL_NAME

    session = AgentSession("item-1", "handler-1")
    session._schedule_pending_command_recheck = lambda *args, **kwargs: None
    session._get_log_line_count = lambda: 0

    session._set_pending_command(
        EXECUTE_COMMAND_TOOL_NAME,
        {"command": "java -jar paper-server.jar nogui"},
    )

    assert session._validate_terminal_command_input(
        EXECUTE_COMMAND_TOOL_NAME,
        {"command": "op Steve"},
    ) is None

    warning = session._validate_terminal_command_input(
        EXECUTE_COMMAND_TOOL_NAME,
        {"command": "ls -la"},
    )

    assert warning is not None
    assert "paper-server.jar" in warning
    assert "ls -la" in warning
