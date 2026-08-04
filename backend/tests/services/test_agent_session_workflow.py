from types import SimpleNamespace

from app.services.agent.reply_ticket import reply_ticket_manager
from app.services.agent.session import AgentSession, InputMessage, InputType


def test_agent_session_converts_dsml_content_into_tool_call() -> None:
    session = AgentSession("item-1", "handler-1")
    message = SimpleNamespace(
        content="""<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="mcp_local_run_job">
<｜｜DSML｜｜parameter name="action" string="true">complete_current_step</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="note" string="true">Java 安装完成</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>""",
        tool_calls=None,
    )
    tools = [
        {
            "type": "function",
            "function": {"name": "mcp_local_run_job"},
        }
    ]

    normalized = session._normalize_dsml_tool_message(message, tools)

    assert normalized.content == ""
    assert len(normalized.tool_calls) == 1
    assert (
        normalized.tool_calls[0].function.name
        == "mcp_local_run_job"
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


