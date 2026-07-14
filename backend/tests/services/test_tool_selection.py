from __future__ import annotations

from types import SimpleNamespace

from app.services.agent.task_workflow import task_workflow_manager
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
    _tool("mcp_local_read_pending_replies"),
    _tool("mcp_local_write_pending_reply"),
    _tool("mcp_local_delete_pending_reply"),
    _tool("mcp_local_send_pending_reply"),
    _tool("mcp_local_get_task_workflow"),
    _tool("mcp_local_update_task_workflow"),
    _tool("mcp_local_save_memory"),
    _tool("mcp_local_recall_memory"),
    _tool("mcp_local_list_memories"),
    _tool("mcp_local_delete_memory"),
    _tool("mcp_local_list_scheduled_tasks"),
    _tool("mcp_local_write_scheduled_task"),
    _tool("mcp_local_delete_scheduled_task"),
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
        "mcp_local_read_pending_replies",
        "mcp_local_write_pending_reply",
        "mcp_local_delete_pending_reply",
        "mcp_local_send_pending_reply",
    ]


def test_web_memory_request_keeps_only_memory_tools() -> None:
    selected = select_tools_for_turn(ALL_TOOLS, source="web", query="记住我喜欢蓝色")

    assert _names(selected) == [
        "mcp_local_save_memory",
        "mcp_local_recall_memory",
        "mcp_local_list_memories",
        "mcp_local_delete_memory",
    ]


def test_schedule_request_keeps_only_schedule_tools() -> None:
    selected = select_tools_for_turn(
        ALL_TOOLS,
        source="web",
        query="创建一个每天九点执行的定时任务",
    )

    assert _names(selected) == [
        "mcp_local_list_scheduled_tasks",
        "mcp_local_write_scheduled_task",
        "mcp_local_delete_scheduled_task",
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


def test_active_workflow_keeps_control_tools_on_follow_up_turn() -> None:
    task_workflow_manager.reset()
    task_workflow_manager.create(
        item_id="item-java",
        handler_id="handler-java",
        reply_ticket_id="ticket-java",
        objective="install Java 17",
        source_type="qq",
        source_label="QQ private:2537134688",
        step_titles=["install Java", "verify Java"],
    )
    agent = SimpleNamespace(
        _context=SimpleNamespace(reply_ticket_id="ticket-java")
    )

    selected = select_tools_for_turn(
        ALL_TOOLS,
        source="qq",
        query="继续",
        agent=agent,
    )

    assert "mcp_local_get_task_workflow" in _names(selected)
    assert "mcp_local_update_task_workflow" in _names(selected)
    assert "mcp_local_list_reply_tickets" in _names(selected)
    assert "mcp_local_read_pending_replies" in _names(selected)
    assert "mcp_local_write_pending_reply" in _names(selected)
    assert "mcp_local_send_pending_reply" in _names(selected)
    task_workflow_manager.reset()


def test_explicit_ticket_keeps_workflow_tools_when_agent_context_is_stale() -> None:
    task_workflow_manager.reset()
    task_workflow_manager.create(
        item_id="item-java",
        handler_id="handler-java",
        reply_ticket_id="ticket-current",
        objective="install Java 17",
        source_type="qq",
        source_label="QQ private:2537134688",
        step_titles=["install Java", "verify Java"],
    )
    agent = SimpleNamespace(
        _context=SimpleNamespace(reply_ticket_id="ticket-from-another-turn")
    )

    selected = select_tools_for_turn(
        ALL_TOOLS,
        source="qq",
        query="background job completed",
        agent=agent,
        reply_ticket_id="ticket-current",
    )

    assert "mcp_local_update_task_workflow" in _names(selected)
    assert "mcp_local_send_pending_reply" in _names(selected)
    task_workflow_manager.reset()


def test_delegated_qq_question_keeps_terminal_and_pending_reply_tools() -> None:
    selected = select_tools_for_turn(
        ALL_TOOLS,
        source="qq",
        query="\u4f60\u95ee\u95ee\u6c49\u5821\u732a\u8981\u73a9\u5230\u51e0\u70b9",
    )
    names = _names(selected)

    assert "mcp_robot_send_message" in names
    assert "mcp_local_execute_command" in names
    assert "mcp_local_read_pending_replies" in names
    assert "mcp_local_write_pending_reply" in names
    assert "mcp_local_send_pending_reply" in names
