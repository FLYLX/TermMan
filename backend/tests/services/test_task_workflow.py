from types import SimpleNamespace

from app.services.agent.task_workflow import TaskWorkflowManager


def _create_java_workflow(manager: TaskWorkflowManager):
    return manager.create(
        item_id="item-java",
        handler_id="handler-java",
        reply_ticket_id="ticket-java",
        objective="安装 Temurin Java 17，使用可用的国内源",
        source_type="qq",
        source_label="QQ group:770362397",
        step_titles=["安装 Temurin Java 17", "验证 java -version"],
    )


def test_recovery_step_returns_to_immutable_main_objective() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)

    manager.record_tool_call(
        "ticket-java",
        tool_name="mcp_local_run_job",
        command="apt-get install -y temurin-17-jdk",
    )
    manager.record_job_result(
        "ticket-java",
        command="apt-get install -y temurin-17-jdk",
        success=False,
        result_summary="Unable to locate package temurin-17-jdk",
        exit_code=100,
    )
    inserted, _ = manager.update(
        "ticket-java",
        action="insert_recovery_step",
        title="切换到可用的国内软件源并更新索引",
        note="当前源没有 temurin-17-jdk",
    )

    assert inserted is True
    assert workflow.objective == "安装 Temurin Java 17，使用可用的国内源"
    # Failed step is cancelled, recovery step is INSERTED (not overwriting)
    assert workflow.steps[0].status == "cancelled"
    assert workflow.current_step().recovery is True
    assert workflow.current_step().title == "切换到可用的国内软件源并更新索引"
    # The original verification step is preserved after the recovery step
    assert len(workflow.steps) == 3
    assert workflow.steps[2].title == "验证 java -version"

    manager.update(
        "ticket-java",
        action="complete_current_step",
        note="国内源已写入，apt-get update 成功",
    )

    # After completing recovery, advances to the preserved verification step
    assert workflow.status == "active"
    assert workflow.current_step().title == "验证 java -version"
    assert workflow.objective == "安装 Temurin Java 17，使用可用的国内源"

    # Complete verification to reach ready_to_report
    manager.record_tool_call(
        "ticket-java",
        tool_name="mcp_local_run_job",
        command="java -version",
    )
    manager.update(
        "ticket-java",
        action="complete_current_step",
        note='openjdk version "17.0.12"',
    )
    assert workflow.status == "ready_to_report"


def test_workflow_completes_only_after_verification_and_delivery() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)

    manager.update(
        "ticket-java",
        action="complete_current_step",
        note="Temurin Java 17 installed successfully",
    )
    assert workflow.status == "active"
    assert workflow.current_step().title == "验证 java -version"

    manager.record_tool_call(
        "ticket-java",
        tool_name="mcp_local_run_job",
        command="java -version",
    )
    manager.update(
        "ticket-java",
        action="complete_current_step",
        note='openjdk version "17.0.12"',
    )
    assert workflow.status == "ready_to_report"
    assert manager.can_finalize("ticket-java") == (True, "")

    snapshot = manager.snapshot_for_ticket("ticket-java")
    assert snapshot is not None
    assert snapshot["status"] == "ready_to_report"
    assert snapshot["delivered_at"] is None

    manager.on_delivery("ticket-java")

    assert workflow.status == "completed"
    assert workflow.delivered_at is not None


def test_unfinished_workflow_requires_execution_instead_of_next_step_narration() -> None:
    manager = TaskWorkflowManager()
    _create_java_workflow(manager)

    can_finalize, correction = manager.can_finalize("ticket-java")

    assert can_finalize is False
    assert "Call one concrete execution tool now" in correction
    assert "Package, mirror, dependency" in correction


def test_auto_resume_is_bounded_and_resets_on_new_evidence() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)

    assert manager.claim_auto_resume("ticket-java") is True
    assert manager.claim_auto_resume("ticket-java") is True
    assert manager.claim_auto_resume("ticket-java") is True
    assert workflow.auto_resume_attempts == 3

    manager.record_job_result(
        "ticket-java",
        command="apt-get install -y openjdk-17-jdk",
        success=False,
        result_summary="Unable to locate package",
        exit_code=100,
    )

    assert workflow.auto_resume_attempts == 0
    assert manager.claim_auto_resume("ticket-java") is True


def test_reset_discards_active_workflow() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)
    manager.update(
        "ticket-java",
        action="record_progress",
        note="正在切换软件源",
    )

    manager.reset()

    assert manager.get(workflow.workflow_id) is None
    assert manager.get_by_ticket("ticket-java") is None


def test_follow_up_ticket_reattaches_same_workflow() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)
    manager.update(
        "ticket-java",
        action="mark_blocked",
        note="当前软件源不可用",
    )

    resumable = manager.find_resumable(
        item_id="item-java",
        source_type="qq",
        source_label="QQ group:770362397",
    )
    assert resumable is workflow

    assert manager.attach_ticket(workflow.workflow_id, "ticket-follow-up") is True
    manager.update(
        "ticket-follow-up",
        action="resume",
        note="用户要求换国内源继续",
    )

    assert manager.get_by_ticket("ticket-java") is workflow
    assert manager.get_by_ticket("ticket-follow-up") is workflow
    assert workflow.status == "active"
    assert workflow.objective == "安装 Temurin Java 17，使用可用的国内源"


def test_recoverable_terminal_wait_cannot_finalize_and_resume_clears_wait() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)

    assert manager.mark_waiting(
        "ticket-java",
        awaiting_kind="terminal_connection",
        awaiting_key="item-java",
        note="终端未连接或未打开",
    ) is True

    assert workflow.status == "blocked"
    assert workflow.queue_status == "waiting"
    assert workflow.awaiting_kind == "terminal_connection"
    assert workflow.current_step().status == "waiting"
    can_finalize, reason = manager.can_finalize("ticket-java")
    assert can_finalize is False
    assert "terminal_connection" in reason

    manager.on_delivery("ticket-java")
    assert workflow.status == "blocked"
    assert workflow.delivered_at is None

    assert manager.attach_ticket(workflow.workflow_id, "ticket-opened") is True
    resumed, _ = manager.update(
        "ticket-opened",
        action="resume",
        note="用户已打开终端，继续安装",
    )

    assert resumed is True
    assert workflow.status == "active"
    assert workflow.queue_status == "working"
    assert workflow.awaiting_kind == ""
    assert workflow.awaiting_key == ""
    assert workflow.current_step().status == "running"


def test_independent_workflows_can_have_parallel_background_jobs() -> None:
    manager = TaskWorkflowManager()
    first = _create_java_workflow(manager)
    second = manager.create(
        item_id="item-java",
        handler_id="handler-java",
        reply_ticket_id="ticket-download",
        objective="下载独立配置包",
        source_type="qq",
        source_label="QQ private:2537134688",
        step_titles=["下载配置包", "验证文件"],
    )

    manager.mark_job_started(
        first.reply_ticket_id,
        command="apt-get install -y openjdk-17-jdk",
    )
    manager.mark_job_started(
        second.reply_ticket_id,
        command="curl -O https://example.invalid/config.zip",
    )

    assert first.status == "waiting_job"
    assert second.status == "waiting_job"
    assert first.jobs[-1].status == "running"
    assert second.jobs[-1].status == "running"


def test_full_task_workflow_is_loaded_only_for_linked_turn() -> None:
    from app.services.agent.prompts import builder as prompt_builder
    from app.services.agent.task_workflow import task_workflow_manager

    task_workflow_manager.reset()
    workflow = _create_java_workflow(task_workflow_manager)
    agent = SimpleNamespace(
        _context=SimpleNamespace(reply_ticket_id="casual-ticket")
    )
    try:
        assert prompt_builder._build_active_task_ledger_context(
            "item-java",
            agent,
        ) == ""

        agent._context.reply_ticket_id = workflow.reply_ticket_id
        task_prompt = prompt_builder._build_active_task_ledger_context(
            "item-java",
            agent,
        )

        assert "Authoritative task workflow" in task_prompt
        assert "安装 Temurin Java 17" in task_prompt
    finally:
        task_workflow_manager.reset()

def test_job_result_does_not_wake_agent_after_workflow_finished() -> None:
    """A finished/delivered workflow must not trigger more agent turns.

    Regression test for the 27-round loop: redundant background verification
    jobs kept completing and each completion woke the agent again even though
    the task was already reported and done.
    """
    manager = TaskWorkflowManager()
    _create_java_workflow(manager)

    # Active workflow still needs job results -> wake the agent.
    assert manager.job_result_needs_new_turn("ticket-java") is True

    # Complete both steps -> ready_to_report (not final yet, report pending).
    manager.update("ticket-java", action="complete_current_step", note="installed")
    manager.update("ticket-java", action="complete_current_step", note="verified")
    assert manager.job_result_needs_new_turn("ticket-java") is True

    # Deliver the report -> workflow completed -> stop waking the agent.
    manager.on_delivery("ticket-java")
    workflow = manager.get_by_ticket("ticket-java")
    assert workflow.status == "completed"
    assert manager.job_result_needs_new_turn("ticket-java") is False

    # Cancelled / failed workflows also stop waking the agent.
    manager2 = TaskWorkflowManager()
    _create_java_workflow(manager2)
    manager2.update("ticket-java", action="cancel", note="user cancelled")
    assert manager2.job_result_needs_new_turn("ticket-java") is False


def test_job_result_does_not_wake_agent_after_delivery_timestamp() -> None:
    manager = TaskWorkflowManager()
    _create_java_workflow(manager)
    manager.on_delivery("ticket-java")
    workflow = manager.get_by_ticket("ticket-java")
    assert workflow.delivered_at is not None
    assert manager.job_result_needs_new_turn("ticket-java") is False
