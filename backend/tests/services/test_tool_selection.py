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
    _tool("mcp_local_list_jobs"),
    _tool("mcp_local_cancel_job"),
    _tool("mcp_local_read_terminal_log"),
    _tool("mcp_local_read_chat_history"),
    _tool("mcp_local_save_memory"),
    _tool("mcp_local_recall_memory"),
    _tool("mcp_local_list_memories"),
    _tool("mcp_local_delete_memory"),
    _tool("mcp_local_list_scheduled_tasks"),
    _tool("mcp_local_write_scheduled_task"),
    _tool("mcp_local_delete_scheduled_task"),
    _tool("mcp_robot_send_message"),
    _tool("mcp_robot_sleep_conversation"),
    _tool("mcp_robot_read_conversation_memory"),
    _tool("mcp_robot_list_memories"),
    _tool("mcp_robot_recall_memory"),
    _tool("mcp_robot_save_memory"),
]

LOCAL_TOOL_NAMES = [n for n in _names(ALL_TOOLS) if n.startswith("mcp_local_")]
ROBOT_TOOL_NAMES = [n for n in _names(ALL_TOOLS) if n.startswith("mcp_robot_")]


def test_web_casual_turn_includes_local_tools_but_not_robot() -> None:
    agent = SimpleNamespace(_context=SimpleNamespace(robot_id="old-robot"))
    selected = select_tools_for_turn(ALL_TOOLS, source="web", query="\u4f60\u597d", agent=agent)
    names = _names(selected)
    assert "mcp_robot_send_message" not in names
    assert "mcp_local_execute_command" in names


def test_web_action_request_includes_all_local_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="web", query="\u5378\u8f7d Java")
    names = _names(selected)
    for local_name in LOCAL_TOOL_NAMES:
        assert local_name in names


def test_web_follow_up_includes_all_local_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="web", query="\u90a3\u4f60\u505a\u52a8\u4f5c\u554a")
    names = _names(selected)
    assert "mcp_local_execute_command" in names
    assert "mcp_local_run_job" in names


def test_qq_turn_includes_robot_and_local_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="qq", query="\u4f60\u597d")
    names = _names(selected)
    assert "mcp_robot_send_message" in names
    assert "mcp_local_execute_command" in names


def test_terminal_turn_includes_local_but_not_robot() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="terminal", query="server log")
    names = _names(selected)
    assert "mcp_local_execute_command" in names
    assert "mcp_robot_send_message" not in names


def test_web_explicit_qq_request_includes_robot_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="web", query="\u53d1 QQ \u6d88\u606f\u5230\u7fa4\u91cc")
    names = _names(selected)
    assert "mcp_robot_send_message" in names
    assert "mcp_local_execute_command" in names


def test_no_duplicate_tools() -> None:
    doubled = ALL_TOOLS + ALL_TOOLS
    selected = select_tools_for_turn(doubled, source="web", query="test")
    names = _names(selected)
    assert len(names) == len(set(names))
