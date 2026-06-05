import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.api.routes.chat import (
    ROBOT_SEND_TOOL_NAME,
    _robot_delivery_correction_message,
    _should_retry_robot_delivery,
)
from app.plugins.robot.contracts import RobotReplyTarget
from app.services.agent import agent as agent_module
from app.services.agent.agent import AgentContext
from app.services.agent.mcp.types import MCPTool
from app.services.agent.prompts import builder as prompt_builder
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.skills import skill_loader
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
            )
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
        assert tool_names == ["mcp_robot_send_message"]

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

        agent.clear_robot_context()

        assert agent.get_mcp_servers() == []
        assert agent.get_tools_for_litellm() == []
    finally:
        agent.clear_robot_context()
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
        robot_id="robot-1",
    )

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


def test_robot_context_forces_robot_messaging_skill_prompt(monkeypatch) -> None:
    robot_skill = SimpleNamespace(
        skill_id="robot_messaging",
        name="Robot Messaging",
        description="Robot messages",
        category="integration",
        action=SimpleNamespace(prompt="robot messaging prompt body"),
        content="",
    )
    agent = SimpleNamespace(
        get_skills=lambda: [robot_skill],
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

    assert "robot messaging prompt body" in messages[0]["content"]


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

    assert _should_retry_robot_delivery(
        agent=agent,
        messages=messages,
        tools=tools,
        final_response="你好呀~",
        retry_used=False,
    ) is True
    assert _should_retry_robot_delivery(
        agent=agent,
        messages=messages,
        tools=tools,
        final_response="你好呀~",
        retry_used=True,
    ) is False

    correction = _robot_delivery_correction_message("你好呀~")
    assert correction["role"] == "system"
    assert "mcp_robot_send_message" in correction["content"]
    assert "你好呀~" in correction["content"]


def test_robot_context_system_prompt_uses_robot_messaging_skill() -> None:
    skill_loader.reload()
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_reply_context_summary=(
                "Current robot reply target:\n"
                "- conversation: group:g1\n"
                "- sender: Alice (u1)\n"
                "- sender_key: onebot_v11:group:g1:u1\n"
                "- send rule: the model may choose this target or another QQ "
                "conversation visible in context. If multiple QQ conversations are "
                "visible, pass a short `reply_to` reference; when omitting target "
                "fields, the tool sends to this current target."
            ),
        ),
        get_skills=lambda: [],
    )

    prompt = get_system_prompt(agent)

    assert "Robot Messaging Skill" in prompt
    assert "Current robot reply target" in prompt
    assert "conversation: group:g1" in prompt
    assert "sender: Alice (u1)" in prompt
    assert "final assistant message is internal" in prompt
    assert "mcp_robot_send_message" in prompt
    assert "Decide which QQ conversation should receive" in prompt


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
