import pytest

from app.services.agent.tool_arguments import (
    ToolArgumentParseError,
    parse_tool_arguments,
)


def test_parse_tool_arguments_accepts_standard_json() -> None:
    assert parse_tool_arguments("mcp_robot_send_message", '{"text":"在呢"}') == {
        "text": "在呢"
    }


def test_parse_robot_send_message_accepts_plain_json_string() -> None:
    assert parse_tool_arguments("mcp_robot_send_message", '"在呢"') == {
        "text": "在呢"
    }


def test_parse_robot_send_message_accepts_text_assignment() -> None:
    assert parse_tool_arguments("mcp_robot_send_message", "text=在呢") == {
        "text": "在呢"
    }


def test_parse_robot_send_message_accepts_code_fenced_json() -> None:
    raw = """```json
{"messages":["在呢", "怎么啦"]}
```"""
    assert parse_tool_arguments("mcp_robot_send_message", raw) == {
        "messages": ["在呢", "怎么啦"]
    }


def test_parse_robot_send_message_accepts_single_quoted_dict() -> None:
    assert parse_tool_arguments("mcp_robot_send_message", "{'message': '没有不理你'}") == {
        "text": "没有不理你"
    }


def test_parse_tool_arguments_rejects_plain_text_for_other_tools() -> None:
    with pytest.raises(ToolArgumentParseError):
        parse_tool_arguments("mcp_local_read_terminal_log", "随便看看")