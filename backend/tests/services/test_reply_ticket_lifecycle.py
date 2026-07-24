from datetime import datetime, timedelta
from types import SimpleNamespace

from app.plugins.robot.api import (
    _merge_active_reply_tickets_into_controller_snapshots,
)
from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.mcp.context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.reply_ticket import ReplyTicketManager
from app.services.agent.task_workflow import task_workflow_manager


def test_qq_reply_ticket_snapshot_keeps_request_and_route_until_delivery() -> None:
    target = RobotReplyTarget(
        target_type="group",
        target_id="770362397",
        metadata={
            "conversation": {"type": "group", "id": "770362397"},
            "sender": {
                "user_id": "2537134688",
                "display_name": "FLY",
            },
            "message": {
                "raw_message": "[CQ:at,qq=2900669542] install temurin 17"
            },
        },
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:770362397:2537134688",
            reply_target=target,
            conversation_key="group:770362397",
            conversation_generation=3,
        )
    )
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_context_token=token,
            reply_ticket_id="",
        )
    )
    manager = ReplyTicketManager()

    try:
        ticket = manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="fallback prompt",
            source_type="qq",
        )
        manager.mark_task_plan(ticket.ticket_id, "plan-1")
        manager.mark_completed(ticket.ticket_id)

        snapshot = manager.snapshot("item-1")
        assert len(snapshot) == 1
        assert snapshot[0]["status"] == "completed"
        assert snapshot[0]["request_message"] == "install temurin 17"
        assert snapshot[0]["sender_label"] == "FLY (2537134688)"
        assert snapshot[0]["conversation_key"] == "group:770362397"

        manager.mark_delivered(ticket.ticket_id)
        assert manager.snapshot("item-1")[0]["status"] == "delivered"
    finally:
        unregister_robot_mcp_context(token)


def test_controller_pending_list_removes_ticket_only_after_delivered(
    monkeypatch,
) -> None:
    base_ticket = {
        "ticket_id": "ticket-1",
        "item_id": "item-1",
        "source_type": "qq",
        "source_label": "QQ group:770362397",
        "status": "completed",
        "task_request_id": "plan-1",
        "request_message": "start the server",
        "command": "bash run.sh",
        "created_at": (datetime.now() - timedelta(seconds=10)).isoformat(),
        "updated_at": datetime.now().isoformat(),
        "delivery_error": "",
        "robot_id": "robot-1",
        "sender_key": "sender-1",
        "sender_label": "FLY (2537134688)",
        "conversation_key": "group:770362397",
        "conversation_generation": 3,
        "workflow": {
            "workflow_id": "workflow-java",
            "objective": "install Java 17",
            "status": "active",
            "current_step": "switch package source",
            "latest_progress": "default source did not contain the package",
            "blocker": "",
            "steps": [
                {
                    "step_id": "step-source",
                    "title": "switch package source",
                    "status": "running",
                    "attempts": 1,
                    "recovery": True,
                }
            ],
        },
    }

    monkeypatch.setattr(
        "app.plugins.robot.api.reply_ticket_manager.snapshot",
        lambda _item_id: [dict(base_ticket)],
    )
    pending_snapshots: dict[str, list[dict[str, object]]] = {}
    _merge_active_reply_tickets_into_controller_snapshots(
        pending_snapshots,
        item_id="item-1",
        robot_ids={"robot-1"},
    )

    pending = pending_snapshots["robot-1"][0]["pending_messages"]
    assert len(pending) == 1
    assert pending[0]["reply_ticket_id"] == "ticket-1"
    assert pending[0]["reply_ticket_status"] == "completed"
    assert pending[0]["task_request_id"] == "plan-1"
    assert pending[0]["workflow_objective"] == "install Java 17"
    assert pending[0]["workflow_current_step"] == "switch package source"
    assert pending[0]["workflow_steps"][0]["recovery"] is True

    monkeypatch.setattr(
        "app.plugins.robot.api.reply_ticket_manager.snapshot",
        lambda _item_id: [{**base_ticket, "status": "delivered"}],
    )
    delivered_snapshots: dict[str, list[dict[str, object]]] = {}
    _merge_active_reply_tickets_into_controller_snapshots(
        delivered_snapshots,
        item_id="item-1",
        robot_ids={"robot-1"},
    )

    assert delivered_snapshots == {}


def test_reply_ticket_pruning_drops_stale_tickets_regardless_of_status() -> None:
    manager = ReplyTicketManager()
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_context_token="",
            reply_ticket_id="",
        )
    )
    stale_pending = manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="stale pending request",
        source_type="web",
    )
    stale_pending.updated_at -= timedelta(hours=7)

    manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="new request",
        source_type="web",
    )
    # A ticket untouched for longer than the TTL will never be delivered and
    # would otherwise fake a permanent "processing" row in the UI.
    assert manager.get(stale_pending.ticket_id) is None

    fresh_pending = manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="fresh pending request",
        source_type="web",
    )
    manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="another request",
        source_type="web",
    )
    assert manager.get(fresh_pending.ticket_id) is fresh_pending


def test_deliver_skips_qq_resend_after_external_report_sent(monkeypatch) -> None:
    target = RobotReplyTarget(
        target_type="group",
        target_id="770362397",
        metadata={
            "conversation": {"type": "group", "id": "770362397"},
            "sender": {"user_id": "2537134688", "display_name": "FLY"},
        },
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:770362397:2537134688",
            reply_target=target,
            conversation_key="group:770362397",
            conversation_generation=3,
        )
    )
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_context_token=token,
            reply_ticket_id="",
        )
    )
    manager = ReplyTicketManager()
    try:
        ticket = manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="speedtest",
            source_type="qq",
        )
        manager.mark_external_report_sent(ticket.ticket_id)

        sent: list[tuple] = []
        monkeypatch.setattr(
            "app.plugins.robot.bridge_client.robot_bridge_client.send_message",
            lambda *args: sent.append(args),
        )

        # The result already reached QQ via the send tool, so this bookkeeping
        # delivery (workflow closure after a watchdog resume) must finalize
        # the ticket silently instead of re-sending a duplicate report.
        assert manager.deliver(ticket.ticket_id, "收尾旁白") is True
        assert sent == []
        assert manager.get(ticket.ticket_id).status == "delivered"
    finally:
        unregister_robot_mcp_context(token)


def test_intermediate_delivery_cannot_close_active_task_workflow() -> None:
    task_workflow_manager.reset()
    manager = ReplyTicketManager()
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_context_token="",
            reply_ticket_id="",
        )
    )
    ticket = manager.create_for_agent(
        agent,
        item_id="item-java",
        handler_id="handler-java",
        message="install Java 17",
        source_type="web",
    )
    task_workflow_manager.create(
        item_id="item-java",
        handler_id="handler-java",
        reply_ticket_id=ticket.ticket_id,
        objective="install Java 17",
        source_type="web",
        source_label="TermMan web chat",
        step_titles=["install Java", "verify Java"],
    )

    assert manager.mark_delivered(ticket.ticket_id) is False
    assert manager.get(ticket.ticket_id).status == "pending"

    task_workflow_manager.update(
        ticket.ticket_id,
        action="complete_current_step",
        note="Java installed",
    )
    task_workflow_manager.record_tool_call(
        ticket.ticket_id,
        tool_name="mcp_local_run_job",
        command="java -version",
    )
    task_workflow_manager.update(
        ticket.ticket_id,
        action="complete_current_step",
        note='openjdk version "17"',
    )

    assert manager.mark_delivered(ticket.ticket_id) is True
    assert manager.get(ticket.ticket_id).status == "delivered"
    assert task_workflow_manager.get_by_ticket(ticket.ticket_id).status == "completed"
    task_workflow_manager.reset()
