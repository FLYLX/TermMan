from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.plugins.robot import service as robot_service_module
from app.plugins.robot.contracts import RobotReplyTarget
from app.services.agent import reply_ticket as reply_ticket_module
from app.services.agent import state_store, task_watchdog
from app.services.agent import task_workflow as task_workflow_module
from app.services.agent.reply_ticket import reply_ticket_manager
from app.services.agent.task_workflow import task_workflow_manager
from tests.utils.item import create_random_item
from tests.utils.robot import create_random_robot


@pytest.fixture(autouse=True)
def isolated_state_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings,
        "AGENT_STATE_STORE_PATH",
        str(tmp_path / "agent_state.db"),
    )
    # Keep watchdog passes hermetic: never touch the real vector store.
    monkeypatch.setattr(
        task_watchdog,
        "_dedupe_memory_clusters",
        lambda now, stats: None,
    )
    state_store.reset_state_store_engine()
    reply_ticket_manager.reset()
    yield
    reply_ticket_manager.reset()
    state_store.reset_state_store_engine()


def _make_agent():
    return SimpleNamespace(_context=None)


def test_workflow_persists_and_restores_with_interruption_normalized() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="ticket-1",
        objective="安装 Java",
        source_type="qq",
        source_label="QQ group:g1",
        step_titles=["安装", "验证"],
    )
    task_workflow_manager.mark_job_started(
        "ticket-1",
        command="apt install openjdk-17-jre",
    )
    assert task_workflow_manager.get(workflow.workflow_id).status == "waiting_job"
    assert state_store.load_workflows(), "workflow row should be persisted"

    # Simulate process death: in-memory state is gone, the store survives.
    task_workflow_manager._workflows.clear()
    task_workflow_manager._ticket_to_workflow.clear()
    assert task_workflow_manager.get(workflow.workflow_id) is None

    restored = task_workflow_module.restore_workflows_from_store()
    assert restored == 1
    revived = task_workflow_manager.get(workflow.workflow_id)
    assert revived is not None
    assert revived.status == "active"
    assert revived.jobs[-1].status == "failed"
    assert revived.jobs[-1].success is False
    assert "Interrupted" in revived.jobs[-1].result_summary
    assert task_workflow_manager.get_by_ticket("ticket-1") is not None


def test_final_workflow_is_not_restored() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="ticket-9",
        objective="已取消的任务",
        source_type="web",
        source_label="web",
        step_titles=["一步"],
    )
    task_workflow_manager.update("ticket-9", action="cancel", note="不要了")
    task_workflow_manager.reset()

    restored = task_workflow_module.restore_workflows_from_store()
    assert restored == 0
    assert task_workflow_manager.get(workflow.workflow_id) is None
    assert state_store.load_workflows() == []


def test_ticket_persists_and_restores_with_aliases() -> None:
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="装一下 java",
    )
    reply_ticket_manager.mark_task_plan(ticket.ticket_id, "plan-1")
    second = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="继续",
    )
    with reply_ticket_manager._lock:
        reply_ticket_manager._ticket_aliases[ticket.ticket_id] = second.ticket_id
        reply_ticket_module._persist_aliases(reply_ticket_manager._ticket_aliases)
    assert state_store.load_tickets(), "ticket rows should be persisted"

    # Simulate process death: in-memory state is gone, the store survives.
    reply_ticket_manager._tickets.clear()
    reply_ticket_manager._ticket_aliases.clear()
    assert reply_ticket_manager.get(second.ticket_id) is None

    restored = reply_ticket_module.restore_tickets_from_store()
    assert restored >= 1
    revived = reply_ticket_manager.get(second.ticket_id)
    assert revived is not None
    assert reply_ticket_manager._tickets[ticket.ticket_id].task_request_id == "plan-1"
    assert reply_ticket_manager.resolve_ticket_id(ticket.ticket_id) == second.ticket_id


def _make_dispatch_job() -> robot_service_module.QueuedRobotChatJob:
    return robot_service_module.QueuedRobotChatJob(
        robot_id=uuid.uuid4(),
        robot_owner_id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        route_key="group:g1",
        message="[Current QQ message]\n装java",
        sender_key="onebot_v11:group:g1:u1",
        reply_target=RobotReplyTarget(
            target_type="group",
            target_id="g1",
            metadata={},
        ),
        conversation_key="group:g1",
        enqueued_at=datetime.now(timezone.utc),
        direct_reply_trigger=True,
        message_text="装java",
        trigger_reason="mentioned",
    )


def test_dispatch_queue_is_memory_only(monkeypatch) -> None:
    service = robot_service_module.RobotService()
    monkeypatch.setattr(service, "_ensure_dispatch_workers", lambda: None)
    assert service._enqueue_chat_job(_make_dispatch_job()) is True
    assert service._dispatch_queue.qsize() == 1
    # A "restarted" service starts empty: dispatch jobs are intentionally
    # not persisted or restored, so a restart never replays stale jobs.
    fresh = robot_service_module.RobotService()
    assert fresh._dispatch_queue.qsize() == 0


def test_chat_job_times_out_and_reports(db: Session, monkeypatch) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    monkeypatch.setattr(settings, "ROBOT_BACKEND_JOB_TIMEOUT_SECONDS", 0.2)

    service = robot_service_module.RobotService()

    async def slow_chat(**_kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(service, "_chat_with_item", slow_chat)
    monkeypatch.setattr(service, "_prepare_queued_chat_message", lambda **_kwargs: "msg")
    monkeypatch.setattr(
        service,
        "conversation_controller_allows_reply",
        lambda *args, **kwargs: True,
    )
    errors: list[str] = []
    monkeypatch.setattr(
        service,
        "_record_and_send_job_error",
        lambda _job, message, **_kwargs: errors.append(message),
    )

    job = robot_service_module.QueuedRobotChatJob(
        robot_id=robot.id,
        robot_owner_id=robot.owner_id,
        item_id=item.id,
        route_key="group:g1",
        message="[Current QQ message]\n装java",
        sender_key="onebot_v11:group:g1:u1",
        reply_target=RobotReplyTarget(
            target_type="group",
            target_id="g1",
            metadata={},
        ),
        conversation_key="group:g1",
        enqueued_at=datetime.now(timezone.utc),
        direct_reply_trigger=True,
        message_text="装java",
    )
    service._process_chat_job(job)
    assert errors and "超时" in errors[0]


def test_watchdog_closes_stale_workflow_and_reports(monkeypatch) -> None:
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="装java",
    )
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id=ticket.ticket_id,
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装"],
    )
    workflow.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)

    sent: list[tuple[str, str]] = []

    def fake_deliver(ticket_id, content):
        sent.append((ticket_id, content))
        return True

    monkeypatch.setattr(reply_ticket_manager, "deliver", fake_deliver)

    stats = task_watchdog.run_once()
    assert stats["closed"] == 1
    assert stats["reported"] == 1
    assert sent and sent[0][0] == ticket.ticket_id
    assert "已自动关闭" in sent[0][1]
    assert workflow.status == "cancelled"


def test_watchdog_keeps_fresh_workflow() -> None:
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="装java",
    )
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id=ticket.ticket_id,
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装"],
    )

    stats = task_watchdog.run_once()
    assert stats["closed"] == 0
    assert stats["orphan_tickets_removed"] == 0
    assert workflow.status == "active"
    assert reply_ticket_manager.get(ticket.ticket_id) is not None


def test_watchdog_removes_stale_inactive_ticket() -> None:
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="随便聊聊",
    )
    stored = reply_ticket_manager.get(ticket.ticket_id)
    assert stored is not None
    stored.updated_at = datetime.now() - timedelta(hours=7)

    stats = task_watchdog.run_once()
    assert stats["orphan_tickets_removed"] == 1
    assert reply_ticket_manager.get(ticket.ticket_id) is None
    assert state_store.load_tickets() == []


def test_deliver_sends_qq_ticket_via_bridge(monkeypatch) -> None:
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.conversation_memory import robot_conversation_memory
    from app.services.agent.reply_ticket import ReplyTicket, reply_ticket_manager

    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda robot_id, target, text: sent.append(
            (robot_id, target.target_id, text)
        ),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda *args, **kwargs: None,
    )
    ticket = ReplyTicket(
        ticket_id="t-qq-1",
        item_id="item-1",
        handler_id="handler-1",
        source_type="qq",
        source_label="QQ group:g1",
        robot_id="robot-1",
        conversation_key="group:g1",
        reply_target={"target_type": "group", "target_id": "g1", "metadata": {}},
    )
    with reply_ticket_manager._lock:
        reply_ticket_manager._tickets[ticket.ticket_id] = ticket

    assert reply_ticket_manager.deliver(ticket.ticket_id, "装好了") is True
    assert sent == [("robot-1", "g1", "装好了")]
    assert reply_ticket_manager.get(ticket.ticket_id).status == "delivered"


def _make_waiting_job_workflow(command: str = "apt-get update"):
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-job-1",
        objective="安装 Java",
        source_type="qq",
        source_label="QQ private:u1",
        step_titles=["apt update", "安装 temurin"],
    )
    task_workflow_manager.mark_job_started("t-job-1", command=command)
    workflow.jobs[-1].started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    return workflow


def test_watchdog_reconciles_lost_background_job_and_resumes(monkeypatch) -> None:
    workflow = _make_waiting_job_workflow()
    monkeypatch.setattr(
        task_watchdog,
        "_get_daemon_connection_for_item",
        lambda _item_id: object(),
    )
    monkeypatch.setattr(
        task_watchdog, "_list_daemon_job_commands", lambda _conn, _item_id: set()
    )
    resumed: list[str] = []
    monkeypatch.setattr(
        task_watchdog,
        "_schedule_workflow_continuation",
        lambda _item_id, ticket_id: resumed.append(ticket_id) or True,
    )

    stats = task_watchdog.run_once()

    assert stats["reconciled"] == 1
    assert stats["resumed"] == 1
    assert workflow.jobs[-1].status == "failed"
    assert "结果丢失" in workflow.jobs[-1].result_summary
    assert workflow.status == "active"
    assert resumed == ["t-job-1"]


def test_watchdog_keeps_job_when_daemon_still_tracks_it(monkeypatch) -> None:
    workflow = _make_waiting_job_workflow()
    monkeypatch.setattr(
        task_watchdog,
        "_get_daemon_connection_for_item",
        lambda _item_id: object(),
    )
    monkeypatch.setattr(
        task_watchdog,
        "_list_daemon_job_commands",
        lambda _conn, _item_id: {"apt-get update"},
    )

    stats = task_watchdog.run_once()

    assert stats["reconciled"] == 0
    assert stats["resumed"] == 0
    assert workflow.jobs[-1].status == "running"
    assert workflow.status == "waiting_job"


def test_watchdog_skips_reconcile_when_daemon_unavailable(monkeypatch) -> None:
    workflow = _make_waiting_job_workflow()
    monkeypatch.setattr(
        task_watchdog,
        "_get_daemon_connection_for_item",
        lambda _item_id: object(),
    )
    monkeypatch.setattr(
        task_watchdog,
        "_list_daemon_job_commands",
        lambda _conn, _item_id: None,
    )

    stats = task_watchdog.run_once()

    assert stats["reconciled"] == 0
    assert workflow.jobs[-1].status == "running"
    assert workflow.status == "waiting_job"


def test_watchdog_recovers_buffered_job_result_from_daemon(monkeypatch) -> None:
    workflow = _make_waiting_job_workflow()
    task_workflow_manager.attach_daemon_job_id(
        "t-job-1", command="apt-get update", daemon_job_id="daemon-job-9"
    )
    result = {
        "success": True,
        "job_id": "daemon-job-9",
        "command": "apt-get update",
        "exit_code": 0,
        "timed_out": False,
        "duration_seconds": 2.0,
        "output_tail": "Reading package lists... Done",
    }

    class FakeConnection:
        def get_job_result_http(self, **_kwargs):
            return {"success": True, "status": "finished", "result": result}

    monkeypatch.setattr(
        task_watchdog,
        "_get_daemon_connection_for_item",
        lambda _item_id: FakeConnection(),
    )
    resumed: list[str] = []
    monkeypatch.setattr(
        task_watchdog,
        "_schedule_workflow_continuation",
        lambda _item_id, ticket_id: resumed.append(ticket_id) or True,
    )

    stats = task_watchdog.run_once()

    assert stats["reconciled"] == 1
    assert stats["resumed"] == 1
    assert workflow.jobs[-1].status == "succeeded"
    assert workflow.jobs[-1].daemon_job_id == "daemon-job-9"
    assert workflow.status == "active"
    assert resumed == ["t-job-1"]


def test_watchdog_marks_job_lost_when_daemon_has_no_record(monkeypatch) -> None:
    workflow = _make_waiting_job_workflow()
    task_workflow_manager.attach_daemon_job_id(
        "t-job-1", command="apt-get update", daemon_job_id="daemon-job-9"
    )

    class FakeConnection:
        def get_job_result_http(self, **_kwargs):
            return {"success": False, "status": "unknown", "job_id": "daemon-job-9"}

    monkeypatch.setattr(
        task_watchdog,
        "_get_daemon_connection_for_item",
        lambda _item_id: FakeConnection(),
    )
    resumed: list[str] = []
    monkeypatch.setattr(
        task_watchdog,
        "_schedule_workflow_continuation",
        lambda _item_id, ticket_id: resumed.append(ticket_id) or True,
    )

    stats = task_watchdog.run_once()

    assert stats["reconciled"] == 1
    assert stats["resumed"] == 1
    assert workflow.jobs[-1].status == "failed"
    assert "结果丢失" in workflow.jobs[-1].result_summary


def test_delivery_on_last_step_closes_workflow() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-final-1",
        objective="安装 Java",
        source_type="qq",
        source_label="QQ private:u1",
        step_titles=["安装", "验证"],
    )
    task_workflow_manager.update("t-final-1", action="complete_current_step", note="装好")
    assert workflow.status == "active"
    assert workflow.current_step_index == 1
    task_workflow_manager.record_tool_call(
        "t-final-1",
        tool_name="mcp_local_execute_command",
        command="java -version",
    )

    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="装好了吗",
    )
    reply_ticket_manager.attach_to_agent(agent, ticket.ticket_id)
    task_workflow_manager.attach_ticket(workflow.workflow_id, ticket.ticket_id)

    assert reply_ticket_manager.mark_delivered(ticket.ticket_id) is True
    assert workflow.steps[-1].status == "completed"
    assert workflow.status == "completed"
    assert workflow.delivered_at is not None


def test_delivery_before_last_step_keeps_workflow_active() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-mid-1",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装", "验证"],
    )
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="进展如何",
    )
    task_workflow_manager.attach_ticket(workflow.workflow_id, ticket.ticket_id)

    assert reply_ticket_manager.mark_delivered(ticket.ticket_id) is False
    assert workflow.status == "active"
    assert workflow.steps[0].status == "running"


def test_duplicate_recovery_step_is_resumed_not_inserted() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-rec-1",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装", "验证"],
    )
    task_workflow_manager.update(
        "t-rec-1",
        action="insert_recovery_step",
        title="改用 openjdk-21 安装",
    )
    task_workflow_manager.update(
        "t-rec-1",
        action="insert_recovery_step",
        title="改用 openjdk-21 安装",
    )
    recovery_titles = [step.title for step in workflow.steps if step.recovery]
    assert recovery_titles == ["改用 openjdk-21 安装"]
    assert workflow.steps[workflow.current_step_index].title == "改用 openjdk-21 安装"


def test_prompt_context_skips_finished_workflow() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-done-1",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["一步"],
    )
    assert task_workflow_manager.build_prompt_context(
        item_id="item-1",
        reply_ticket_id="t-done-1",
    )
    task_workflow_manager.update("t-done-1", action="cancel", note="不做了")
    assert (
        task_workflow_manager.build_prompt_context(
            item_id="item-1",
            reply_ticket_id="t-done-1",
        )
        == ""
    )


def test_watchdog_resumes_stalled_active_workflow(monkeypatch) -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-stall-1",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装", "验证"],
    )
    workflow.updated_at = datetime.now(timezone.utc) - timedelta(minutes=15)

    monkeypatch.setattr(task_watchdog, "_item_has_live_execution", lambda _item_id: False)
    resumed: list[str] = []
    monkeypatch.setattr(
        task_watchdog,
        "_schedule_workflow_continuation",
        lambda _item_id, ticket_id: resumed.append(ticket_id) or True,
    )

    stats = task_watchdog.run_once()

    assert stats["stalled_resumed"] == 1
    assert resumed == ["t-stall-1"]
    assert workflow.status == "active"


def test_watchdog_skips_stalled_when_execution_live(monkeypatch) -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-stall-2",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装", "验证"],
    )
    workflow.updated_at = datetime.now(timezone.utc) - timedelta(minutes=15)

    monkeypatch.setattr(task_watchdog, "_item_has_live_execution", lambda _item_id: True)
    resumed: list[str] = []
    monkeypatch.setattr(
        task_watchdog,
        "_schedule_workflow_continuation",
        lambda _item_id, ticket_id: resumed.append(ticket_id) or True,
    )

    stats = task_watchdog.run_once()

    assert stats["stalled_resumed"] == 0
    assert resumed == []


def test_watchdog_skips_stalled_when_job_running(monkeypatch) -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-stall-3",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装", "验证"],
    )
    task_workflow_manager.mark_job_started("t-stall-3", command="apt-get update")
    workflow.updated_at = datetime.now(timezone.utc) - timedelta(minutes=15)

    monkeypatch.setattr(task_watchdog, "_item_has_live_execution", lambda _item_id: False)
    monkeypatch.setattr(
        task_watchdog,
        "_list_daemon_job_commands",
        lambda _item_id: {"apt-get update"},
    )
    resumed: list[str] = []
    monkeypatch.setattr(
        task_watchdog,
        "_schedule_workflow_continuation",
        lambda _item_id, ticket_id: resumed.append(ticket_id) or True,
    )

    stats = task_watchdog.run_once()

    assert stats["stalled_resumed"] == 0
    assert resumed == []


def test_watchdog_skips_stalled_when_fresh(monkeypatch) -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-stall-4",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装", "验证"],
    )

    monkeypatch.setattr(task_watchdog, "_item_has_live_execution", lambda _item_id: False)
    resumed: list[str] = []
    monkeypatch.setattr(
        task_watchdog,
        "_schedule_workflow_continuation",
        lambda _item_id, ticket_id: resumed.append(ticket_id) or True,
    )

    stats = task_watchdog.run_once()

    assert stats["stalled_resumed"] == 0
    assert resumed == []


def test_delivery_on_unattached_ticket_closes_last_step_workflow() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-orig-1",
        objective="安装 Java",
        source_type="qq",
        source_label="QQ private:u1",
        step_titles=["安装", "验证"],
    )
    task_workflow_manager.update("t-orig-1", action="complete_current_step", note="装好")
    assert workflow.current_step_index == 1
    assert workflow.status == "active"
    task_workflow_manager.record_tool_call(
        "t-orig-1",
        tool_name="mcp_local_execute_command",
        command="java -version",
    )

    # A follow-up question creates a fresh ticket that is NOT attached to the
    # workflow. The agent answers "验证过了" on that ticket and it delivers.
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="验证过了吗",
    )
    assert task_workflow_manager.get_by_ticket(ticket.ticket_id) is None

    assert reply_ticket_manager.mark_delivered(ticket.ticket_id) is True
    assert workflow.steps[-1].status == "completed"
    assert workflow.status == "completed"
    assert workflow.delivered_at is not None


def test_unattached_delivery_does_not_close_mid_workflow() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-orig-2",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["安装", "验证"],
    )
    assert workflow.current_step_index == 0

    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="进展如何",
    )

    assert reply_ticket_manager.mark_delivered(ticket.ticket_id) is True
    assert workflow.status == "active"
    assert workflow.steps[0].status == "running"


def test_verification_step_requires_fresh_tool_evidence() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-verify-1",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["检查系统是否已安装Java", "安装Java（如未安装）", "验证Java安装"],
    )

    # Verbal completion without running any tool must be rejected.
    ok, detail = task_workflow_manager.update(
        "t-verify-1",
        action="complete_current_step",
        note="记忆里装过",
    )
    assert ok is False
    assert "evidence" in detail.lower() or "证据" in detail
    assert workflow.steps[0].status == "running"

    # After actually calling a tool this run, completion is allowed.
    task_workflow_manager.record_tool_call(
        "t-verify-1",
        tool_name="mcp_local_execute_command",
        command="java -version",
    )
    task_workflow_manager.record_tool_result(
        "t-verify-1",
        tool_name="mcp_local_execute_command",
        success=False,
        result_summary="java: command not found",
    )
    ok, _ = task_workflow_manager.update(
        "t-verify-1",
        action="complete_current_step",
        note="java -version 显示未安装",
    )
    assert ok is True
    assert workflow.steps[0].status == "completed"


def test_delivery_does_not_close_evidence_less_verification_step() -> None:
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id="t-verify-2",
        objective="安装 Java",
        source_type="web",
        source_label="web",
        step_titles=["验证Java安装"],
    )
    assert workflow.current_step_index == 0

    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="验证过了吗",
    )

    # The agent claims "verified" from memory without running any check:
    # delivery succeeds but the verification step must NOT auto-complete.
    assert reply_ticket_manager.mark_delivered(ticket.ticket_id) is True
    assert workflow.status == "active"
    assert workflow.steps[0].status == "running"

    # Once a check actually ran this run, delivery closes the workflow.
    task_workflow_manager.record_tool_call(
        "t-verify-2",
        tool_name="mcp_local_execute_command",
        command="java -version",
    )
    task_workflow_manager.record_tool_result(
        "t-verify-2",
        tool_name="mcp_local_execute_command",
        success=True,
        result_summary='openjdk version "21.0.11"',
    )
    ticket2 = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="确认一下",
    )
    assert reply_ticket_manager.mark_delivered(ticket2.ticket_id) is True
    assert workflow.steps[0].status == "completed"
    assert workflow.status == "completed"
