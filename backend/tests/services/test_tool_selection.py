from __future__ import annotations

from types import SimpleNamespace

from app.services.agent.tool_selection import select_tools_for_turn


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _names(tools: list[dict]) -> list[str]:
    return [tool["function"]["name"] for tool in tools]


ALL_TOOLS = [
    _tool("mcp_local_execute_command"),
    _tool("mcp_local_run_job"),
    _tool("mcp_local_read_terminal_log"),
    _tool("mcp_local_read_chat_history"),
    _tool("mcp_local_list_reply_tickets"),
    _tool("mcp_local_save_memory"),
    _tool("mcp_local_recall_memory"),
    _tool("mcp_local_list_memories"),
    _tool("mcp_local_delete_memory"),
    _tool("mcp_robot_send_message"),
    _tool("mcp_robot_sleep_conversation"),
]


def test_web_casual_turn_does_not_inherit_stale_robot_context() -> None:
    agent = SimpleNamespace(_context=SimpleNamespace(robot_id="old-robot"))

    selected = select_tools_for_turn(
        ALL_TOOLS,
        source="web",
        query="你好",
        agent=agent,
    )

    assert _names(selected) == []


def test_qq_casual_turn_keeps_only_robot_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="qq", query="你好")

    assert _names(selected) == [
        "mcp_robot_send_message",
        "mcp_robot_sleep_conversation",
    ]


def test_qq_terminal_request_keeps_robot_and_local_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="qq", query="安装 java 17")
    names = _names(selected)

    assert "mcp_robot_send_message" in names
    assert "mcp_local_execute_command" in names
    assert "mcp_local_run_job" in names
    assert "mcp_local_read_terminal_log" in names


def test_web_history_request_keeps_only_history_tools() -> None:
    selected = select_tools_for_turn(
        ALL_TOOLS,
        source="web",
        query="刚才待回复列表里有什么",
    )

    assert _names(selected) == [
        "mcp_local_read_chat_history",
        "mcp_local_list_reply_tickets",
    ]


def test_web_memory_request_keeps_only_memory_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="web", query="记住我喜欢蓝色")

    assert _names(selected) == [
        "mcp_local_save_memory",
        "mcp_local_recall_memory",
        "mcp_local_list_memories",
        "mcp_local_delete_memory",
    ]


def test_web_explicit_qq_request_keeps_robot_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="web", query="发 QQ 消息到群里")

    assert _names(selected) == [
        "mcp_robot_send_message",
        "mcp_robot_sleep_conversation",
    ]


def test_terminal_turn_keeps_local_tools_only() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="terminal", query="server log")
    names = _names(selected)

    assert "mcp_local_execute_command" in names
    assert "mcp_local_run_job" in names
    assert "mcp_local_read_terminal_log" in names
    assert "mcp_robot_send_message" not in names
