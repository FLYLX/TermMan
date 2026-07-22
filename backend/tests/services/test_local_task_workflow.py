import threading

from app.services.agent.mcp.local_server import LocalMCPServer
from app.services.agent.task_workflow import task_workflow_manager


def test_local_mcp_exposes_authoritative_workflow_tools() -> None:
    server = LocalMCPServer()
    names = {tool["name"] for tool in server.list_tools()}

    assert "get_task_workflow" in names
    assert "update_task_workflow" in names


def test_local_mcp_updates_current_workflow_step() -> None:
    task_workflow_manager.reset()
    task_workflow_manager.create(
        item_id="item-java",
        handler_id="handler-java",
        reply_ticket_id="ticket-java",
        objective="install Java 17",
        source_type="web",
        source_label="TermMan web chat",
        step_titles=["install Java", "verify Java"],
    )
    server = LocalMCPServer()

    result = server._update_task_workflow(
        {
            "item_id": "item-java",
            "_reply_ticket_id": "ticket-java",
            "action": "complete_current_step",
            "note": "Temurin package installed",
        }
    )

    assert "Task workflow updated: active" in result[0]["text"]
    workflow = task_workflow_manager.get_by_ticket("ticket-java")
    assert workflow is not None
    assert workflow.current_step().title == "verify Java"
    task_workflow_manager.reset()


def test_background_job_result_resumes_agent_with_original_ticket(
    monkeypatch,
) -> None:
    task_workflow_manager.reset()
    task_workflow_manager.create(
        item_id="item-java",
        handler_id="handler-java",
        reply_ticket_id="ticket-java",
        objective="install Java 17",
        source_type="web",
        source_label="TermMan web chat",
        step_titles=["install Java", "verify Java"],
    )
    task_workflow_manager.mark_job_started(
        "ticket-java",
        command="apt-get update",
    )
    server = LocalMCPServer()
    completed = threading.Event()
    captured = {}

    class FakeConnection:
        def run_job_http(self, **_kwargs):
            return {"success": True, "job_id": "daemon-job-1"}

        def get_job_result_http(self, **_kwargs):
            return {
                "success": True,
                "status": "finished",
                "result": {
                    "success": True,
                    "command": "apt-get update",
                    "job_id": "daemon-job-1",
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_seconds": 2.5,
                    "output_tail": "Reading package lists... Done",
                },
            }

    class FakeAgentSession:
        def clear_terminal_job(self, command):
            captured["cleared_command"] = command

        def record_finished_job(self, command, **kwargs):
            pass

        def process_input(self, input_message):
            captured["input"] = input_message
            completed.set()

    monkeypatch.setattr(
        server,
        "_deliver_background_job_to_reply_ticket",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("active Agent session must continue the workflow first")
        ),
    )

    server._start_background_job_thread(
        item_id="item-java",
        command="apt-get update",
        connection=FakeConnection(),
        request_kwargs={},
        agent_session=FakeAgentSession(),
        reply_ticket_id="ticket-java",
    )

    assert completed.wait(timeout=2) is True
    assert captured["cleared_command"] == "apt-get update"
    assert captured["input"].reply_ticket_id == "ticket-java"
    assert "Background terminal job completed" in captured["input"].content
    workflow = task_workflow_manager.get_by_ticket("ticket-java")
    assert workflow is not None
    assert workflow.status == "active"
    assert workflow.jobs[-1].status == "succeeded"
    assert workflow.jobs[-1].daemon_job_id == "daemon-job-1"
    assert workflow.objective == "install Java 17"
    task_workflow_manager.reset()
