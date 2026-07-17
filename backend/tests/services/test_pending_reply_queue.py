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


def test_pending_task_rebinds_to_follow_up_ticket_without_losing_plan() -> None:
    manager = ReplyTicketManager()
    task_workflow_manager.reset()
    first = manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="Install Java",
        source_type="web",
    )
    second = manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="Continue",
        source_type="web",
    )
    try:
        manager.upsert_pending_reply(
            first.ticket_id,
            request_summary="Install Java",
            task_plan=["Install Java", "Verify version", "Report result"],
        )
        workflow = task_workflow_manager.get_by_ticket(first.ticket_id)
        assert workflow is not None

        assert task_workflow_manager.attach_ticket(
            workflow.workflow_id,
            second.ticket_id,
        ) is True
        assert manager.rebind_pending_reply(first.ticket_id, second.ticket_id) is True

        entries = manager.list_pending_replies("item-1")
        assert len(entries) == 1
        assert entries[0]["id"] == second.ticket_id
        assert entries[0]["request_summary"] == "Install Java"
        assert entries[0]["task_plan"] == [
            "Install Java",
            "Verify version",
            "Report result",
        ]
        assert manager.resolve_ticket_id(first.ticket_id) == second.ticket_id
        assert manager.get(first.ticket_id) is second
        assert task_workflow_manager.get_by_ticket(first.ticket_id) is workflow
    finally:
        task_workflow_manager.reset()


def test_background_job_old_ticket_alias_updates_current_workflow() -> None:
    manager = ReplyTicketManager()
    task_workflow_manager.reset()
    first = manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="安装 Java",
        source_type="web",
    )
    second = manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="直接换成国内源",
        source_type="web",
    )
    try:
        manager.upsert_pending_reply(
            first.ticket_id,
            request_summary="安装 Java",
            task_plan=["安装 Java", "验证 java -version"],
        )
        workflow = task_workflow_manager.get_by_ticket(first.ticket_id)
        assert workflow is not None
        task_workflow_manager.mark_job_started(
            first.ticket_id,
            command="apt-get install -y openjdk-17-jdk",
        )

        assert task_workflow_manager.attach_ticket(
            workflow.workflow_id,
            second.ticket_id,
        ) is True
        assert manager.rebind_pending_reply(first.ticket_id, second.ticket_id) is True

        task_workflow_manager.record_job_result(
            first.ticket_id,
            command="apt-get install -y openjdk-17-jdk",
            success=False,
            result_summary="Unable to locate package openjdk-17-jdk",
            exit_code=100,
        )

        assert manager.get(first.ticket_id) is second
        assert workflow.reply_ticket_id == second.ticket_id
        assert workflow.status == "active"
        assert "Unable to locate package" in workflow.latest_progress
    finally:
        task_workflow_manager.reset()


def test_pending_reply_broadcasts_created_updated_and_removed_events(
    monkeypatch,
) -> None:
    from app.services.agent.stream_manager import stream_manager

    manager = ReplyTicketManager()
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        stream_manager,
        "broadcast_chat_event",
        lambda item_id, event: events.append((item_id, event)),
    )
    ticket = manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="Install Java",
        source_type="web",
    )

    manager.upsert_pending_reply(ticket.ticket_id, status="working")
    manager.upsert_pending_reply(ticket.ticket_id, status="waiting")
    assert manager.delete_pending_reply(ticket.ticket_id) is True

    assert [event[1]["action"] for event in events] == [
        "created",
        "updated",
        "removed",
    ]
    assert all(event[0] == "item-1" for event in events)
    assert all(event[1]["type"] == "task_queue_changed" for event in events)


def test_pending_reply_sends_to_original_qq_then_removes_entry(monkeypatch) -> None:
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.conversation_memory import robot_conversation_memory
    from app.services.agent.stream_manager import stream_manager

    manager = ReplyTicketManager()
    token, ticket = _create_qq_ticket(manager)
    sent: list[tuple[str, str, str]] = []
    memory: list[tuple[str, str, str]] = []
    lifecycle: list[str] = []
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda robot_id, target, text: (
            lifecycle.append("delivered"),
            sent.append((str(robot_id), target.target_id, text)),
        ),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda robot_id, conversation_key, text: memory.append(
            (str(robot_id), conversation_key, text)
        ),
    )
    monkeypatch.setattr(
        stream_manager,
        "broadcast_chat_event",
        lambda _item_id, event: lifecycle.append(str(event.get("action") or "")),
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
        assert lifecycle == ["created", "updated", "delivered", "removed"]
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


def test_failed_task_report_retries_then_removes_and_finalizes(monkeypatch) -> None:
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.conversation_memory import robot_conversation_memory

    manager = ReplyTicketManager()
    token, ticket = _create_qq_ticket(manager)
    attempts = 0

    def send_message(*_args, **_kwargs) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("bridge offline")

    monkeypatch.setattr(robot_bridge_client, "send_message", send_message)
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda *_args, **_kwargs: None,
    )
    task_workflow_manager.reset()
    try:
        workflow = task_workflow_manager.create(
            item_id="item-1",
            handler_id="handler-1",
            reply_ticket_id=ticket.ticket_id,
            objective="Install Java",
            source_type="qq",
            source_label="QQ group:770362397",
            step_titles=["Install Java", "Report result"],
        )
        manager.upsert_pending_reply(ticket.ticket_id, status="working")
        task_workflow_manager.update(
            ticket.ticket_id,
            action="mark_blocked",
            note="Package source is unavailable",
        )

        delivered, detail = manager.send_pending_reply(
            ticket.ticket_id,
            "Java installation failed because the package source is unavailable.",
        )

        assert delivered is False
        assert "bridge offline" in detail
        assert len(manager.list_pending_replies("item-1")) == 1
        assert workflow.status == "blocked"

        delivered, _ = manager.send_pending_reply(
            ticket.ticket_id,
            "Java installation failed because the package source is unavailable.",
        )

        assert delivered is True
        assert attempts == 2
        assert manager.list_pending_replies("item-1") == []
        assert workflow.status == "failed"
    finally:
        unregister_robot_mcp_context(token)
        task_workflow_manager.reset()


def test_pending_reply_rejects_dsml_trace_and_keeps_entry() -> None:
    manager = ReplyTicketManager()
    ticket = manager.create_for_agent(
        _agent(),
        item_id="item-1",
        handler_id="handler-1",
        message="Install Java",
        source_type="web",
    )
    manager.upsert_pending_reply(ticket.ticket_id, status="ready")

    delivered, detail = manager.send_pending_reply(
        ticket.ticket_id,
        """<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="mcp_local_update_task_workflow">
<｜｜DSML｜｜parameter name="action" string="true">complete_current_step</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>""",
    )

    assert delivered is False
    assert detail == "reply content contains no visible text"
    assert manager.get(ticket.ticket_id) is ticket
    assert manager.list_pending_replies("item-1")[0]["status"] == "ready"


def test_final_qq_delivery_uses_explicit_ticket_when_agent_context_is_stale(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.conversation_memory import robot_conversation_memory

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    token, ticket = _create_qq_ticket(reply_ticket_manager)
    agent = _agent(robot_id="robot-1", token=token)
    agent._context.reply_ticket_id = "stale-ticket-from-another-turn"
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda _robot_id, target, text: sent.append((target.target_id, text)),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        chat_route,
        "_persist_and_broadcast_event",
        lambda _item_id, **event: event,
    )

    try:
        events = chat_route._deliver_reply_ticket_final_response(
            agent=agent,
            item_id="item-1",
            content="Java 17 已安装完成。",
            include_hidden_tool_results=False,
            reply_ticket_id=ticket.ticket_id,
        )

        assert sent == [("770362397", "Java 17 已安装完成。")]
        assert events[0]["content"] == "已回复 QQ：Java 17 已安装完成。"
        assert reply_ticket_manager.get(ticket.ticket_id).status == "delivered"
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


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
    assert "awaiting=minecraft_player:yueyinghanbo" in prompt
    assert "mcp_local_send_pending_reply" in prompt


def test_casual_prompt_hides_unrelated_task_details_and_loads_selected_task() -> None:
    manager = ReplyTicketManager()
    ticket_ids: list[str] = []
    for index in range(10):
        ticket = manager.create_for_agent(
            _agent(),
            item_id="item-1",
            handler_id="handler-1",
            message=f"task {index}",
            source_type="web",
        )
        manager.upsert_pending_reply(ticket.ticket_id, status="working")
        ticket_ids.append(ticket.ticket_id)

    compact_prompt = manager.build_pending_reply_prompt("item-1")
    selected_prompt = manager.build_pending_reply_prompt(
        "item-1",
        current_ticket_id=ticket_ids[0],
    )

    assert "Background task index: 10 unfinished task(s)." in compact_prompt
    assert "not linked to any background task" in compact_prompt
    assert "task 0" not in compact_prompt
    assert all(ticket_id not in compact_prompt for ticket_id in ticket_ids)
    assert len(compact_prompt) < 1200
    assert "Authoritative task queue entry for this turn" in selected_prompt
    assert ticket_ids[0] in selected_prompt
    assert "task 0" in selected_prompt
    assert ticket_ids[-1] not in selected_prompt


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


def test_delegated_question_enters_task_queue_with_workflow(
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
        entry = reply_ticket_manager.list_pending_replies("item-1")[0]
        assert entry["id"] == ticket.ticket_id
        assert entry["request_summary"] == "你问问汉堡猪要玩到几点"
        assert entry["task_plan"] == [
            "Ask player",
            "Wait for response",
            "Report result",
        ]
        assert task_workflow_manager.get_by_ticket(ticket.ticket_id) is not None
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_qq_task_plan_enters_queue_with_original_qq_destination(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    token, ticket = _create_qq_ticket(reply_ticket_manager)
    agent = _agent(robot_id="robot-1", token=token)
    agent._context.reply_ticket_id = "stale-ticket-from-another-turn"
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda *args, **kwargs: ["Install Java", "Verify Java", "Report result"],
    )

    try:
        runtime = chat_route._create_agent_task_plan(
            "item-1",
            handler=SimpleNamespace(id="handler-1"),
            agent=agent,
            message="下 Java 17",
            history=[],
            tools=[
                {
                    "type": "function",
                    "function": {"name": "mcp_local_run_job"},
                }
            ],
            reply_ticket_id=ticket.ticket_id,
        )

        assert runtime is not None
        entries = reply_ticket_manager.list_pending_replies("item-1")
        assert len(entries) == 1
        assert entries[0]["id"] == ticket.ticket_id
        assert entries[0]["destination_type"] == "qq"
        assert entries[0]["destination_label"] == "QQ group:770362397"
        assert entries[0]["requester"] == "FLY (2537134688)"
        assert entries[0]["task_plan"] == [
            "Install Java",
            "Verify Java",
            "Report result",
        ]
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_confirmed_external_delivery_removes_pending_after_workflow_finishes() -> None:
    from app.api.routes.chat import _complete_confirmed_external_delivery

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    agent = _agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="发群里说个你好",
        source_type="web",
    )
    reply_ticket_manager.upsert_pending_reply(
        ticket.ticket_id,
        request_summary="发群里说个你好",
        task_plan=["发送消息", "确认发送"],
        status="working",
    )
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id=ticket.ticket_id,
        objective="发群里说个你好",
        source_type="web",
        source_label="TermMan web chat",
        step_titles=["发送消息", "确认发送"],
    )

    try:
        assert _complete_confirmed_external_delivery(ticket.ticket_id) is False
        assert reply_ticket_manager.list_pending_replies("item-1")

        task_workflow_manager.update(
            ticket.ticket_id,
            action="complete_current_step",
            note="QQ send succeeded",
        )
        task_workflow_manager.update(
            ticket.ticket_id,
            action="complete_current_step",
            note="Send result confirmed",
        )

        assert _complete_confirmed_external_delivery(ticket.ticket_id) is True
        assert reply_ticket_manager.get(ticket.ticket_id) is None
        assert reply_ticket_manager.list_pending_replies("item-1") == []
        assert task_workflow_manager.get(workflow.workflow_id).status == "completed"
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()
