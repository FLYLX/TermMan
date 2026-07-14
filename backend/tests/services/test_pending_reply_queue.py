from types import SimpleNamespace

from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.mcp.context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.mcp.local_server import LocalMCPServer
from app.services.agent.reply_ticket import (
    ReplyTicketManager,
    reply_ticket_manager,
)
from app.services.agent.session import AgentSession, PendingCommand
from app.services.agent.task_workflow import task_workflow_manager


def _agent(*, robot_id: str = "", token: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        _context=SimpleNamespace(
            robot_id=robot_id,
            robot_context_token=token,
            reply_ticket_id="",
        )
    )


def _create_qq_ticket(
    manager: ReplyTicketManager,
) -> tuple[str, object]:
    target = RobotReplyTarget(
        target_type="group",
        target_id="770362397",
        metadata={
            "conversation": {"type": "group", "id": "770362397"},
            "sender": {"user_id": "2537134688", "display_name": "FLY"},
            "message": {
                "raw_message": (
                    "[CQ:at,qq=2900669542] "
                    "\u4f60\u95ee\u95ee\u6c49\u5821\u732a\u8981\u73a9\u5230\u51e0\u70b9"
                )
            },
        },
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:770362397:2537134688",
            reply_target=target,
            conversation_key="group:770362397",
            conversation_generation=4,
        )
    )
    ticket = manager.create_for_agent(
        _agent(robot_id="robot-1", token=token),
        item_id="item-1",
        handler_id="handler-1",
        message="fallback",
        source_type="qq",
    )
    return token, ticket


def test_pending_reply_locks_requester_plan_and_destination() -> None:
    manager = ReplyTicketManager()
    token, ticket = _create_qq_ticket(manager)
    try:
        entry = manager.upsert_pending_reply(
            ticket.ticket_id,
            requester="FLY (2537134688)",
            request_summary="Ask the Minecraft player when they will stop playing.",
            task_plan=["Ask player", "Wait for response", "Report to QQ"],
        )

        assert entry["requester"] == "FLY (2537134688)"
        assert entry["task_plan"] == [
            "Ask player",
            "Wait for response",
            "Report to QQ",
        ]
        assert entry["destination_type"] == "qq"
        assert "770362397" in entry["destination_label"]
        assert manager.list_pending_replies("item-1") == [entry]
    finally:
        unregister_robot_mcp_context(token)


def test_pending_reply_sends_to_original_qq_then_removes_entry(monkeypatch) -> None:
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.conversation_memory import robot_conversation_memory

    manager = ReplyTicketManager()
    token, ticket = _create_qq_ticket(manager)
    sent: list[tuple[str, str, str]] = []
    memory: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda robot_id, target, text: sent.append(
            (str(robot_id), target.target_id, text)
        ),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda robot_id, conversation_key, text: memory.append(
            (str(robot_id), conversation_key, text)
        ),
    )
    try:
        manager.upsert_pending_reply(ticket.ticket_id, status="ready")
        delivered, destination = manager.send_pending_reply(
            ticket.ticket_id,
            "The player said they will play until bedtime.",
        )

        assert delivered is True
        assert "770362397" in destination
        assert sent == [
            (
                "robot-1",
                "770362397",
                "The player said they will play until bedtime.",
            )
        ]
        assert memory == [
            (
                "robot-1",
                "group:770362397",
                "The player said they will play until bedtime.",
            )
        ]
        assert manager.get(ticket.ticket_id) is None
    finally:
        unregister_robot_mcp_context(token)


def test_pending_reply_delivery_failure_keeps_entry(monkeypatch) -> None:
    from app.plugins.robot.bridge_client import robot_bridge_client

    manager = ReplyTicketManager()
    token, ticket = _create_qq_ticket(manager)

    def fail_send(*_args, **_kwargs):
        raise RuntimeError("bridge offline")

    monkeypatch.setattr(robot_bridge_client, "send_message", fail_send)
    try:
        manager.upsert_pending_reply(ticket.ticket_id, status="ready")
        delivered, detail = manager.send_pending_reply(
            ticket.ticket_id,
            "Final result",
        )

        assert delivered is False
        assert "bridge offline" in detail
        remaining = manager.list_pending_replies("item-1")
        assert len(remaining) == 1
        assert remaining[0]["status"] == "failed"
        assert remaining[0]["last_error"] == "bridge offline"
    finally:
        unregister_robot_mcp_context(token)


def test_pending_reply_cannot_send_before_workflow_is_finished(monkeypatch) -> None:
    from app.plugins.robot.bridge_client import robot_bridge_client

    task_workflow_manager.reset()
    manager = ReplyTicketManager()
    token, ticket = _create_qq_ticket(manager)
    sent: list[str] = []
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda _robot_id, _target, text: sent.append(text),
    )
    try:
        task_workflow_manager.create(
            item_id="item-1",
            handler_id="handler-1",
            reply_ticket_id=ticket.ticket_id,
            objective="Ask a player and report the response",
            source_type="qq",
            source_label="QQ group:770362397",
            step_titles=["Ask player", "Wait for response", "Report result"],
        )
        manager.upsert_pending_reply(ticket.ticket_id, status="working")

        delivered, detail = manager.send_pending_reply(
            ticket.ticket_id,
            "Premature result",
        )

        assert delivered is False
        assert "not finished" in detail
        assert sent == []
        assert manager.get(ticket.ticket_id) is not None
    finally:
        task_workflow_manager.reset()
        unregister_robot_mcp_context(token)


def test_minecraft_reply_matches_waiting_pending_reply() -> None:
    manager = ReplyTicketManager()
    ticket = manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="Ask player",
        source_type="web",
    )
    manager.upsert_pending_reply(
        ticket.ticket_id,
        status="waiting",
        awaiting_kind="minecraft_player",
        awaiting_key="yueyinghanbo",
    )

    assert manager.match_pending_reply(
        "item-1",
        "[23:17:15] [Server thread/INFO]: <yueyinghanbo> I will play until bedtime",
    )["id"] == ticket.ticket_id
    assert (
        manager.match_pending_reply(
            "item-1",
            "[23:17:16] [Server thread/INFO]: <another_player> unrelated",
        )
        is None
    )
    prompt = manager.build_pending_reply_prompt(
        "item-1",
        current_input="<yueyinghanbo> I will play until bedtime",
    )
    assert "current_input_matches_awaiting=yes" in prompt
    assert "mcp_local_send_pending_reply" in prompt


def test_tell_command_updates_pending_reply_wait_target() -> None:
    reply_ticket_manager.reset()
    ticket = reply_ticket_manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="Ask player",
        source_type="web",
    )
    reply_ticket_manager.upsert_pending_reply(ticket.ticket_id, status="working")
    terminal_session = AgentSession("item-1", "handler-1")
    command = "tell yueyinghanbo When will you stop playing?"
    try:
        terminal_session._update_pending_reply_waiting(
            PendingCommand(
                tool_name="mcp_local_execute_command",
                command=command,
                normalized_command=command.casefold(),
                reply_ticket_id=ticket.ticket_id,
            )
        )
        entry = reply_ticket_manager.list_pending_replies("item-1")[0]
        assert entry["status"] == "waiting"
        assert entry["awaiting_kind"] == "minecraft_player"
        assert entry["awaiting_key"] == "yueyinghanbo"
    finally:
        reply_ticket_manager.reset()


def test_pending_reply_mcp_tools_manage_current_reply_ticket() -> None:
    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    ticket = reply_ticket_manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="Delegated request",
        source_type="web",
    )
    server = LocalMCPServer()
    try:
        saved = server.call_tool(
            "write_pending_reply",
            {
                "item_id": "item-1",
                "entry_id": ticket.ticket_id,
                "requester": "web user",
                "request_summary": "Wait for a player response",
                "task_plan": ["Ask", "Wait", "Report"],
                "status": "waiting",
                "awaiting_kind": "minecraft_player",
                "awaiting_key": "yueyinghanbo",
            },
        )
        assert "Pending reply saved" in saved[0]["text"]

        listed = server.call_tool("read_pending_replies", {"item_id": "item-1"})
        assert ticket.ticket_id in listed[0]["text"]
        assert "yueyinghanbo" in listed[0]["text"]

        deleted = server.call_tool(
            "delete_pending_reply",
            {"item_id": "item-1", "entry_id": ticket.ticket_id},
        )
        assert "Pending reply deleted" in deleted[0]["text"]
        assert reply_ticket_manager.list_pending_replies("item-1") == []

        tool_names = {tool["name"] for tool in server.list_tools()}
        assert {
            "read_pending_replies",
            "write_pending_reply",
            "delete_pending_reply",
            "send_pending_reply",
        }.issubset(tool_names)
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_delegated_question_creates_queue_only_after_agent_requests_it(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    agent = _agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="\u4f60\u95ee\u95ee\u6c49\u5821\u732a\u8981\u73a9\u5230\u51e0\u70b9",
        source_type="web",
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda *args, **kwargs: ["Ask player", "Wait for response", "Report result"],
    )
    monkeypatch.setattr(
        chat_route.vector_store,
        "add_memory",
        lambda *args, **kwargs: None,
    )
    try:
        runtime = chat_route._create_agent_task_plan(
            "item-1",
            handler=SimpleNamespace(id="handler-1"),
            agent=agent,
            message="\u4f60\u95ee\u95ee\u6c49\u5821\u732a\u8981\u73a9\u5230\u51e0\u70b9",
            history=[],
            tools=[{"type": "function"}],
        )

        assert runtime is not None
        assert reply_ticket_manager.list_pending_replies("item-1") == []
        server = LocalMCPServer()
        result = server.call_tool(
            "write_pending_reply",
            {
                "item_id": "item-1",
                "_reply_ticket_id": ticket.ticket_id,
                "request_summary": "你问问汉堡猪要玩到几点",
                "task_plan": ["Ask player", "Wait for response", "Report result"],
                "status": "working",
            },
        )
        assert result[0]["text"].startswith("Pending reply saved:")
        entry = reply_ticket_manager.list_pending_replies("item-1")[0]
        assert entry["id"] == ticket.ticket_id
        assert entry["task_plan"] == [
            "Ask player",
            "Wait for response",
            "Report result",
        ]
        assert task_workflow_manager.get_by_ticket(ticket.ticket_id) is not None
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()
