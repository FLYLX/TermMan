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


def test_recovery_step_returns_to_immutable_main_objective(tmp_path) -> None:
    manager = TaskWorkflowManager(
        state_path=tmp_path / "task-workflows.json",
        persist=True,
    )
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


def test_workflow_completes_only_after_verification_and_delivery(tmp_path) -> None:
    manager = TaskWorkflowManager(
        state_path=tmp_path / "task-workflows.json",
        persist=True,
    )
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


def test_active_workflow_survives_manager_reload(tmp_path) -> None:
    state_path = tmp_path / "task-workflows.json"
    manager = TaskWorkflowManager(state_path=state_path, persist=True)
    workflow = _create_java_workflow(manager)
    manager.update(
        "ticket-java",
        action="record_progress",
        note="正在切换软件源",
    )

    reloaded = TaskWorkflowManager(state_path=state_path, persist=True)
    restored = reloaded.get(workflow.workflow_id)

    assert restored is not None
    assert restored.objective == workflow.objective
    assert restored.latest_progress == "正在切换软件源"
    assert restored.reply_ticket_id == "ticket-java"


def test_follow_up_ticket_reattaches_same_workflow(tmp_path) -> None:
    manager = TaskWorkflowManager(
        state_path=tmp_path / "task-workflows.json",
        persist=False,
    )
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

    assert manager.get_by_ticket("ticket-java") is None
    assert manager.get_by_ticket("ticket-follow-up") is workflow
    assert workflow.status == "active"
    assert workflow.objective == "安装 Temurin Java 17，使用可用的国内源"
