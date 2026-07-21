from types import SimpleNamespace

from app.services.agent.reply_ticket import reply_ticket_manager
from app.services.agent.session import AgentSession, InputMessage, InputType
from app.services.agent.task_workflow import task_workflow_manager


def test_agent_session_converts_dsml_content_into_tool_call() -> None:
    session = AgentSession("item-1", "handler-1")
    message = SimpleNamespace(
        content="""<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="mcp_local_update_task_workflow">
<｜｜DSML｜｜parameter name="action" string="true">complete_current_step</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="note" string="true">Java 安装完成</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>""",
        tool_calls=None,
    )
    tools = [
        {
            "type": "function",
            "function": {"name": "mcp_local_update_task_workflow"},
        }
    ]

    normalized = session._normalize_dsml_tool_message(message, tools)

    assert normalized.content == ""
    assert len(normalized.tool_calls) == 1
    assert (
        normalized.tool_calls[0].function.name
        == "mcp_local_update_task_workflow"
    )
    assert "complete_current_step" in normalized.tool_calls[0].function.arguments


def test_terminal_queue_does_not_merge_different_reply_tickets() -> None:
    session = AgentSession("item-1", "handler-1")
    session.input_queue.put_nowait(
        InputMessage(
            input_type=InputType.TERMINAL,
            content="first job result",
            reply_ticket_id="ticket-a",
        )
    )

    merged = session._merge_terminal_queue_input(
        InputMessage(
            input_type=InputType.TERMINAL,
            content="second job result",
            reply_ticket_id="ticket-b",
        )
    )

    assert merged is False
    assert session.input_queue.queue[0].content == "first job result"


def test_terminal_callback_attaches_original_ticket_during_processing(
    monkeypatch,
) -> None:
    reply_ticket_manager.reset()
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_context_token="",
            reply_ticket_id="",
        )
    )
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="install Java 17",
        source_type="web",
    )
    reply_ticket_manager.detach_from_agent(agent, ticket.ticket_id)
    session = AgentSession("item-1", "handler-1")
    observed: list[str] = []

    monkeypatch.setattr(session, "get_agent", lambda: agent)
    monkeypatch.setattr(
        session,
        "_process_terminal_input",
        lambda _input, current_agent: observed.append(
            current_agent._context.reply_ticket_id
        ),
    )

    session._process_input(
        InputMessage(
            input_type=InputType.TERMINAL,
            content="background job completed",
            reply_ticket_id=ticket.ticket_id,
        )
    )

    assert observed == [ticket.ticket_id]
    assert agent._context.reply_ticket_id == ""
    reply_ticket_manager.reset()


def test_schedule_task_workflow_continuation_is_internal_and_bounded(
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    task_workflow_manager.reset()
    task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="ticket-java",
        objective="安装 Java",
        source_type="qq",
        source_label="QQ private:2537134688",
        step_titles=["安装 Java", "验证 java -version"],
    )
    captured: list[tuple] = []

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            captured.append((target, args, daemon))

        def start(self):
            return None

    monkeypatch.setattr(session_module.threading, "Thread", FakeThread)
    session = AgentSession("item-1", "handler-1")

    try:
        assert session.schedule_task_workflow_continuation("ticket-java") is True
        assert session.schedule_task_workflow_continuation("ticket-java") is True
        assert session.schedule_task_workflow_continuation("ticket-java") is True
        assert session.schedule_task_workflow_continuation("ticket-java") is True
        assert session.schedule_task_workflow_continuation("ticket-java") is True
        assert session.schedule_task_workflow_continuation("ticket-java") is False

        queued_input = captured[0][1][0]
        assert queued_input.input_type == InputType.TASK_CONTINUATION
        assert queued_input.reply_ticket_id == "ticket-java"
        assert "Internal task workflow continuation" in queued_input.content
        assert captured[0][2] is True
    finally:
        task_workflow_manager.reset()



def test_env_prefixed_apt_install_routes_to_background_job() -> None:
    from app.services.agent.session import (
        should_auto_route_terminal_tool_to_job,
        should_route_command_to_background_job,
    )

    assert should_route_command_to_background_job(
        "DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-21-jdk-headless 2>&1 | tail -30"
    ) is True
    assert should_route_command_to_background_job(
        "sudo DEBIAN_FRONTEND=noninteractive apt-get update"
    ) is True
    assert should_auto_route_terminal_tool_to_job(
        "mcp_local_execute_command",
        {"command": "DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-21-jdk-headless"},
    ) is True


def test_interactive_and_short_commands_not_routed() -> None:
    from app.services.agent.session import should_route_command_to_background_job

    assert should_route_command_to_background_job("java -jar server.jar nogui") is False
    assert should_route_command_to_background_job("ls -la") is False
    assert should_route_command_to_background_job("tail -f server.log") is False
