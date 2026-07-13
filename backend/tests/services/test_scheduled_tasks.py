from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.agent.mcp.local_server import LocalMCPServer


def test_scheduled_task_storage_and_mcp_crud(monkeypatch, tmp_path) -> None:
    import app.services.agent.scheduled_tasks as scheduled_tasks

    monkeypatch.setattr(scheduled_tasks, "_SCHEDULED_TASKS_DIR", tmp_path)
    server = LocalMCPServer()

    created = server.call_tool(
        "write_scheduled_task",
        {
            "item_id": "item-1",
            "name": "check server",
            "instruction": "Check whether the Minecraft server is healthy.",
            "schedule_type": "interval",
            "interval_seconds": 300,
            "timezone": "Asia/Shanghai",
        },
    )
    assert "Scheduled task saved" in created[0]["text"]

    tasks = scheduled_tasks.list_scheduled_tasks("item-1")
    assert len(tasks) == 1
    task_id = tasks[0]["id"]
    assert tasks[0]["next_run_at"]

    listed = server.call_tool("list_scheduled_tasks", {"item_id": "item-1"})
    assert task_id in listed[0]["text"]
    assert "check server" in listed[0]["text"]

    updated = server.call_tool(
        "write_scheduled_task",
        {
            "item_id": "item-1",
            "task_id": task_id,
            "name": "check server",
            "instruction": "Check whether the Minecraft server is healthy.",
            "schedule_type": "interval",
            "interval_seconds": 600,
            "enabled": False,
        },
    )
    assert "enabled=False" in updated[0]["text"]
    assert scheduled_tasks.list_scheduled_tasks("item-1")[0]["next_run_at"] is None

    deleted = server.call_tool(
        "delete_scheduled_task",
        {"item_id": "item-1", "task_id": task_id, "reason": "obsolete"},
    )
    assert "Scheduled task deleted" in deleted[0]["text"]
    assert scheduled_tasks.list_scheduled_tasks("item-1") == []


def test_due_task_is_tagged_and_completed_after_agent_turn(monkeypatch, tmp_path) -> None:
    import app.services.agent.scheduled_tasks as scheduled_tasks
    from app.services.agent.session import InputType, agent_session_manager

    monkeypatch.setattr(scheduled_tasks, "_SCHEDULED_TASKS_DIR", tmp_path)
    run_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    task = scheduled_tasks.write_scheduled_task(
        "11111111-1111-1111-1111-111111111111",
        name="one shot",
        instruction="Report current server status.",
        schedule_type="once",
        run_at=run_at,
    )
    claimed = scheduled_tasks._claim_due_tasks(datetime.now(timezone.utc))
    assert len(claimed) == 1

    emitted: list[tuple[str, str, dict | None]] = []
    received = []

    class FakeSession:
        def emit_output(self, content, message_type, extra=None):
            emitted.append((content, message_type, extra))

        def process_input(self, input_message):
            received.append(input_message)
            if input_message.callback:
                input_message.callback(
                    {"type": "agent_response", "content": "Scheduled check complete"}
                )
            if input_message.completion_callback:
                input_message.completion_callback(True, "")

        def remove_output_callback(self, callback):
            return None

    fake_session = FakeSession()
    monkeypatch.setattr(scheduled_tasks, "_handler_id_for_item", lambda item_id: "handler-1")
    monkeypatch.setattr(
        agent_session_manager,
        "get_or_create_session",
        lambda item_id, handler_id: fake_session,
    )

    item_id, claimed_task = claimed[0]
    scheduled_tasks.scheduled_task_manager._dispatch(item_id, claimed_task)

    assert emitted[0][1] == "scheduled_task"
    assert emitted[0][2]["scheduled_task_id"] == task["id"]
    assert received[0].input_type == InputType.SCHEDULED_TASK
    assert received[0].content.startswith("[Scheduled task]")
    assert "mcp_local_delete_scheduled_task" in received[0].content

    finished = scheduled_tasks.list_scheduled_tasks(item_id)[0]
    assert finished["last_status"] == "success"
    assert finished["enabled"] is False
    assert finished["next_run_at"] is None


def test_daily_task_uses_configured_timezone(monkeypatch, tmp_path) -> None:
    import app.services.agent.scheduled_tasks as scheduled_tasks

    monkeypatch.setattr(scheduled_tasks, "_SCHEDULED_TASKS_DIR", tmp_path)
    task = scheduled_tasks.write_scheduled_task(
        "item-daily",
        name="daily report",
        instruction="Summarize terminal status.",
        schedule_type="daily",
        time_of_day="09:30",
        timezone_name="Asia/Shanghai",
    )

    next_run = datetime.fromisoformat(task["next_run_at"])
    assert next_run.tzinfo is not None
    assert task["time_of_day"] == "09:30"
    assert task["timezone"] == "Asia/Shanghai"


def test_scheduled_reply_ticket_keeps_background_result_link(monkeypatch, tmp_path) -> None:
    import app.services.agent.scheduled_tasks as scheduled_tasks
    from app.services.agent.reply_ticket import reply_ticket_manager

    monkeypatch.setattr(scheduled_tasks, "_SCHEDULED_TASKS_DIR", tmp_path)
    reply_ticket_manager.reset()
    task = scheduled_tasks.write_scheduled_task(
        "item-linked",
        name="linked task",
        instruction="Run a background health check.",
        schedule_type="interval",
        interval_seconds=300,
    )
    agent = SimpleNamespace(_context=SimpleNamespace())
    ticket = reply_ticket_manager.create_for_scheduled_task(
        agent,
        item_id="item-linked",
        handler_id="handler-linked",
        message="[Scheduled task] linked task",
        scheduled_task_id=task["id"],
        scheduled_execution_id="execution-1",
    )

    assert ticket.scheduled_task_id == task["id"]
    assert "Authoritative scheduled task ticket" in reply_ticket_manager.build_prompt(
        ticket.ticket_id
    )
    assert scheduled_tasks.record_scheduled_ticket_result(
        ticket.ticket_id,
        success=False,
        error="network timeout",
    )
    updated = scheduled_tasks.list_scheduled_tasks("item-linked")[0]
    assert updated["last_status"] == "failed"
    assert updated["last_error"] == "network timeout"
    reply_ticket_manager.reset()
