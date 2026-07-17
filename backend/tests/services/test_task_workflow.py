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
    assert workflow.current_step().recovery is True

    manager.update(
        "ticket-java",
        action="complete_current_step",
        note="国内源已写入，apt-get update 成功",
    )

    assert workflow.current_step().title == "安装 Temurin Java 17"
    assert workflow.current_step().status == "running"
    assert workflow.objective == "安装 Temurin Java 17，使用可用的国内源"

    can_finalize, correction = manager.can_finalize("ticket-java")
    assert can_finalize is False
    assert "安装 Temurin Java 17" in correction


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


def test_final_only_policy_suppresses_intermediate_delivery_until_ready() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)

    assert manager.set_report_policy("ticket-java", "final_only") is True
    assert workflow.report_policy == "final_only"
    assert manager.should_suppress_intermediate_delivery("ticket-java") is True

    manager.update(
        "ticket-java",
        action="complete_current_step",
        note="Java installed",
    )
    manager.update(
        "ticket-java",
        action="complete_current_step",
        note='openjdk version "17.0.12"',
    )

    assert workflow.status == "ready_to_report"
    assert manager.should_suppress_intermediate_delivery("ticket-java") is False


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

    assert manager.claim_auto_resume("ticket-java", max_attempts=2) is True
    assert manager.claim_auto_resume("ticket-java", max_attempts=2) is True
    assert manager.claim_auto_resume("ticket-java", max_attempts=2) is False
    assert workflow.auto_resume_attempts == 2

    manager.record_job_result(
        "ticket-java",
        command="apt-get install -y openjdk-17-jdk",
        success=False,
        result_summary="Unable to locate package",
        exit_code=100,
    )

    assert workflow.auto_resume_attempts == 0
    assert manager.claim_auto_resume("ticket-java", max_attempts=2) is True


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


def test_terminal_dependency_resumes_only_after_predecessor_clears() -> None:
    manager = TaskWorkflowManager()
    workflow = _create_java_workflow(manager)

    assert manager.mark_waiting(
        "ticket-java",
        awaiting_kind="terminal_dependency",
        awaiting_key="item-java",
        note="前一个终端任务仍在执行",
    ) is True
    assert workflow.status == "blocked"
    assert workflow.current_step().status == "waiting"

    resumed = manager.resume_waiting_dependencies(
        item_id="item-java",
        awaiting_kind="terminal_dependency",
    )

    assert resumed == ["ticket-java"]
    assert workflow.status == "active"
    assert workflow.awaiting_kind == ""
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
