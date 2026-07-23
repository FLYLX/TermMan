"""End-to-end simulation: install Java workflow lifecycle.

Simulates the full path a "install Java" task takes through the workflow
system, background jobs, report delivery, and termination guards.
Verifies no infinite loops, no stuck states, and correct step progression.
"""

from app.services.agent.task_workflow import TaskWorkflowManager


def _create_install_java_workflow(manager: TaskWorkflowManager):
    return manager.create(
        item_id="item-e2e",
        handler_id="handler-e2e",
        reply_ticket_id="ticket-e2e",
        objective="Install OpenJDK 21 and verify",
        source_type="qq",
        source_label="QQ private:2537134688",
        step_titles=[
            "Check current Java status",
            "Switch to Aliyun mirror and apt update",
            "Install openjdk-21-jdk-headless",
            "Verify java -version",
            "Report result to QQ private:2537134688",
        ],
    )


class TestJavaInstallWorkflowLifecycle:
    """Simulate the full install-java workflow from creation to completion."""

    def test_full_happy_path_with_background_jobs(self):
        """Job callback drives each step to completion, report closes workflow."""
        manager = TaskWorkflowManager()
        workflow = _create_install_java_workflow(manager)

        # Step 1: Check current Java status (run_job: java -version)
        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="java -version",
        )
        job_id = manager.register_job_start(
            "ticket-e2e", command="java -version"
        )
        assert workflow.status == "waiting_job"
        assert any(j.status == "running" for j in workflow.jobs)

        # Job callback: java not found
        manager.record_job_result(
            "ticket-e2e",
            command="java -version",
            success=False,
            result_summary="command not found",
            exit_code=127,
        )
        assert workflow.status == "active"
        assert not any(j.status == "running" for j in workflow.jobs)

        # Agent completes step 1
        ok, _ = manager.update(
            "ticket-e2e",
            action="complete_current_step",
            note="Java not installed, proceeding to install",
        )
        assert ok
        assert workflow.current_step_index == 1

        # Step 2: Switch mirror + apt update (run_job)
        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="apt-get update",
        )
        manager.register_job_start("ticket-e2e", command="apt-get update")
        assert workflow.status == "waiting_job"

        manager.record_job_result(
            "ticket-e2e",
            command="apt-get update",
            success=True,
            result_summary="Reading package lists... Done",
            exit_code=0,
        )
        ok, _ = manager.update(
            "ticket-e2e",
            action="complete_current_step",
            note="Aliyun mirror configured, apt update succeeded",
        )
        assert ok
        assert workflow.current_step_index == 2

        # Step 3: Install openjdk-21 (run_job)
        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="apt-get install -y openjdk-21-jdk-headless",
        )
        manager.register_job_start(
            "ticket-e2e",
            command="apt-get install -y openjdk-21-jdk-headless",
        )
        assert workflow.status == "waiting_job"

        manager.record_job_result(
            "ticket-e2e",
            command="apt-get install -y openjdk-21-jdk-headless",
            success=True,
            result_summary="Setting up openjdk-21-jdk-headless (21.0.11+9-1)",
            exit_code=0,
        )
        ok, _ = manager.update(
            "ticket-e2e",
            action="complete_current_step",
            note="openjdk-21 installed successfully",
        )
        assert ok
        assert workflow.current_step_index == 3

        # Step 4: Verify java -version (run_job)
        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="java -version",
        )
        manager.register_job_start("ticket-e2e", command="java -version")
        assert workflow.status == "waiting_job"

        manager.record_job_result(
            "ticket-e2e",
            command="java -version",
            success=True,
            result_summary='openjdk version "21.0.11" 2025-04-15',
            exit_code=0,
        )
        ok, _ = manager.update(
            "ticket-e2e",
            action="complete_current_step",
            note='Verified: openjdk version "21.0.11"',
        )
        assert ok
        assert workflow.current_step_index == 4

        # Step 5: Report step - agent sends QQ message
        # can_finalize should be False (report step not done yet)
        can_finalize, _ = manager.can_finalize("ticket-e2e")
        assert can_finalize is False

        # Simulate: agent calls mcp_robot_send_message -> mark_delivered -> on_delivery
        manager.on_delivery("ticket-e2e")
        assert workflow.status == "completed"
        assert workflow.delivered_at is not None
        assert workflow.report_sent_at is not None
        assert all(
            s.status in {"completed", "cancelled"} for s in workflow.steps
        )

        # After completion: no more wakeups
        assert manager.job_result_needs_new_turn("ticket-e2e") is False
        assert manager.claim_auto_resume("ticket-e2e") is False

    def test_duplicate_job_is_rejected(self):
        """register_job_start rejects exact duplicate running commands."""
        manager = TaskWorkflowManager()
        _create_install_java_workflow(manager)

        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="apt-get install -y openjdk-21-jdk-headless",
        )
        first_id = manager.register_job_start(
            "ticket-e2e",
            command="apt-get install -y openjdk-21-jdk-headless",
        )
        assert first_id != ""

        # Second attempt: same command while first is running
        second_id = manager.register_job_start(
            "ticket-e2e",
            command="apt-get install -y openjdk-21-jdk-headless",
        )
        assert second_id == ""  # rejected

    def test_failed_job_triggers_recovery_not_loop(self):
        """Failed job -> recovery step -> bounded retries, no infinite loop."""
        manager = TaskWorkflowManager()
        workflow = _create_install_java_workflow(manager)

        # Step 1: try install openjdk-17 (will fail)
        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="apt-get install -y openjdk-17-jdk-headless",
        )
        manager.register_job_start(
            "ticket-e2e",
            command="apt-get install -y openjdk-17-jdk-headless",
        )
        manager.record_job_result(
            "ticket-e2e",
            command="apt-get install -y openjdk-17-jdk-headless",
            success=False,
            result_summary="E: Unable to locate package openjdk-17-jdk-headless",
            exit_code=100,
        )

        # Insert recovery step
        ok, _ = manager.update(
            "ticket-e2e",
            action="insert_recovery_step",
            title="Install openjdk-21-jdk-headless instead",
            note="openjdk-17 not available in this repo",
        )
        assert ok
        assert workflow.steps[0].status == "cancelled"
        assert workflow.current_step().recovery is True

        # Auto-resume is bounded
        for i in range(6):
            assert manager.claim_auto_resume("ticket-e2e") is True
        # 7th attempt: blocked
        assert manager.claim_auto_resume("ticket-e2e") is False

    def test_report_sent_blocks_further_wakeups(self):
        """After on_delivery, no job result or auto-resume can wake the agent."""
        manager = TaskWorkflowManager()
        workflow = _create_install_java_workflow(manager)

        # Fast-forward to report step
        for i in range(4):
            step = workflow.current_step()
            if step:
                step.status = "completed"
            workflow.current_step_index = i + 1
        workflow.status = "active"

        # Deliver report
        manager.on_delivery("ticket-e2e")
        assert workflow.status == "completed"

        # All wakeup paths blocked
        assert manager.job_result_needs_new_turn("ticket-e2e") is False
        assert manager.claim_auto_resume("ticket-e2e") is False

    def test_transient_error_keeps_workflow_alive(self):
        """Simulate LLM error: workflow stays active, retry is scheduled."""
        manager = TaskWorkflowManager()
        workflow = _create_install_java_workflow(manager)

        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="apt-get install -y openjdk-21-jdk-headless",
        )
        manager.register_job_start(
            "ticket-e2e",
            command="apt-get install -y openjdk-21-jdk-headless",
        )

        # Job completes successfully
        manager.record_job_result(
            "ticket-e2e",
            command="apt-get install -y openjdk-21-jdk-headless",
            success=True,
            result_summary="Setting up openjdk-21-jdk-headless",
            exit_code=0,
        )

        # Workflow is active, auto_resume_attempts reset by job result
        assert workflow.status == "active"
        assert workflow.auto_resume_attempts == 0

        # Agent can still be resumed (e.g., after transient LLM error)
        assert manager.claim_auto_resume("ticket-e2e") is True
        assert workflow.auto_resume_attempts == 1

        # Workflow NOT cancelled - task survives
        assert workflow.status == "active"
        assert workflow.delivered_at is None

    def test_abort_cancels_workflow(self):
        """Simulate user abort: workflow is cancelled, no resurrection."""
        manager = TaskWorkflowManager()
        workflow = _create_install_java_workflow(manager)

        manager.record_tool_call(
            "ticket-e2e",
            tool_name="mcp_local_run_job",
            command="apt-get install -y openjdk-21-jdk-headless",
        )
        manager.register_job_start(
            "ticket-e2e",
            command="apt-get install -y openjdk-21-jdk-headless",
        )

        # User aborts -> cancel workflow
        ok, _ = manager.update(
            "ticket-e2e",
            action="cancel",
            note="User interrupted the task.",
        )
        assert ok
        assert workflow.status == "cancelled"

        # No wakeup paths work
        assert manager.claim_auto_resume("ticket-e2e") is False
        assert manager.job_result_needs_new_turn("ticket-e2e") is False

    def test_find_related_workflows_detects_same_objective(self):
        """find_related_workflows finds workflows with matching objectives."""
        manager = TaskWorkflowManager()
        first = _create_install_java_workflow(manager)
        manager.on_delivery("ticket-e2e")
        assert first.status == "completed"

        related = manager.find_related_workflows(
            item_id="item-e2e",
            objective="Install OpenJDK 21 and verify",
        )
        assert len(related) == 1
        assert related[0].workflow_id == first.workflow_id

    def test_find_related_workflows_no_match_for_different_objective(self):
        """find_related_workflows returns empty for unrelated objectives."""
        manager = TaskWorkflowManager()
        _create_install_java_workflow(manager)

        related = manager.find_related_workflows(
            item_id="item-e2e",
            objective="Install Python 3.12",
        )
        assert len(related) == 0

    def test_create_allows_duplicate_but_agent_sees_context(self):
        """create() allows duplicates; agent decides via prompt context."""
        manager = TaskWorkflowManager()
        first = _create_install_java_workflow(manager)
        manager.on_delivery("ticket-e2e")

        second = manager.create(
            item_id="item-e2e",
            handler_id="handler-e2e",
            reply_ticket_id="ticket-e2e-dup",
            objective="Install OpenJDK 21 and verify",
            source_type="qq",
            source_label="QQ private:2537134688",
            step_titles=["Check Java", "Install Java", "Report"],
        )

        # New workflow IS created (agent decides, not code)
        assert second.workflow_id != first.workflow_id
        # But find_related_workflows shows the old one for prompt context
        related = manager.find_related_workflows(
            item_id="item-e2e",
            objective="Install OpenJDK 21 and verify",
        )
        assert len(related) == 2

    def test_different_objective_creates_new_workflow(self):
        """Different objective creates a separate workflow."""
        manager = TaskWorkflowManager()
        _create_install_java_workflow(manager)

        second = manager.create(
            item_id="item-e2e",
            handler_id="handler-e2e",
            reply_ticket_id="ticket-python",
            objective="Install Python 3.12",
            source_type="qq",
            source_label="QQ private:2537134688",
            step_titles=["Install Python", "Verify", "Report"],
        )

        # Different objective -> new workflow
        assert second.workflow_id != "ticket-e2e"
        assert second.objective == "Install Python 3.12"

    def test_workflow_serialization_roundtrip(self):
        """Workflow with report_sent_at survives persist/restore cycle."""
        from app.services.agent.task_workflow import (
            workflow_from_payload,
            workflow_to_payload,
        )

        manager = TaskWorkflowManager()
        workflow = _create_install_java_workflow(manager)
        manager.on_delivery("ticket-e2e")

        payload = workflow_to_payload(workflow)
        assert payload["report_sent_at"] is not None
        assert payload["delivered_at"] is not None
        assert payload["status"] == "completed"

        restored = workflow_from_payload(payload)
        assert restored.report_sent_at is not None
        assert restored.delivered_at is not None
        assert restored.status == "completed"
