from app.services.agent.mcp.local_server import LocalMCPServer
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.skills import skill_loader


def test_execute_command_only_reports_dispatch(monkeypatch) -> None:
    import importlib

    import app.services.socket_pool as socket_pool

    input_center_module = importlib.import_module("app.services.socket_pool.input_center")

    sent: dict[str, str] = {}

    class FakeInputSDK:
        def send(self, item_id: str, command: str) -> bool:
            sent["item_id"] = item_id
            sent["command"] = command
            return True

    monkeypatch.setattr(socket_pool, "InputSDK", FakeInputSDK)
    monkeypatch.setattr(input_center_module.input_center, "has_handler", lambda item_id: True)

    server = LocalMCPServer()
    result = server.call_tool(
        "execute_command",
        {
            "item_id": "item-1",
            "command": "echo 23231",
        },
    )

    assert result == [
        {
            "type": "text",
            "text": "命令已发送到终端，尚未确认执行结果: echo 23231",
        }
    ]
    assert sent == {"item_id": "item-1", "command": "echo 23231\n"}
    tool = next(tool for tool in server.list_tools() if tool["name"] == "execute_command")
    props = tool["inputSchema"]["properties"]
    assert "expected_output" in props
    assert "expected_regex" in props
    assert "timeout_seconds" in props
    assert "auto_interrupt_on_timeout" in props
    assert "不要默认用 &&" in tool["description"]
    assert "一次只发一条命令" in tool["description"]
    assert "默认不要拼接" in tool["inputSchema"]["properties"]["command"]["description"]



def test_execute_command_blocks_when_busy_terminal_command_pending(monkeypatch) -> None:
    import importlib

    import app.services.socket_pool as socket_pool
    from app.services.agent.session import EXECUTE_COMMAND_TOOL_NAME, agent_session_manager

    input_center_module = importlib.import_module("app.services.socket_pool.input_center")
    item_id = "item-busy"

    class FakeInputSDK:
        def send(self, item_id: str, command: str) -> bool:
            raise AssertionError("blocked command should not be sent to terminal")

    monkeypatch.setattr(socket_pool, "InputSDK", FakeInputSDK)
    monkeypatch.setattr(input_center_module.input_center, "has_handler", lambda item_id: True)

    agent_session_manager.remove_session(item_id)
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")
    monkeypatch.setattr(session, "_schedule_pending_command_recheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(session, "_get_log_line_count", lambda: 0)
    session.mark_terminal_command_dispatched(
        EXECUTE_COMMAND_TOOL_NAME,
        {"command": "apt update"},
    )

    try:
        server = LocalMCPServer()
        result = server.call_tool(
            "execute_command",
            {
                "item_id": item_id,
                "command": "java -version",
            },
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert len(result) == 1
    assert result[0]["type"] == "text"
    assert "apt update" in result[0]["text"]
    assert "java -version" in result[0]["text"]
    assert "命令未发送" in result[0]["text"]

def test_system_prompt_forbids_claiming_command_success_without_confirmation() -> None:
    skill_loader.reload()
    prompt = get_system_prompt()

    assert "不代表命令执行成功" in prompt
    assert "命令已发送，等待终端结果确认" in prompt
    assert "终端防卡死规则" in prompt
    assert "终端打开不等于 shell 空闲" in prompt
    assert "不要为了试探是否可输入而连续发送" in prompt
    assert "不要拼接 shell 命令" in prompt
    assert "`&&`" in prompt
    assert "mcp_local_interrupt_command" in prompt
    assert "mcp_local_run_job" in prompt
    assert "mcp_local_record_installed_software" in prompt
    assert "mcp_local_remove_installed_software" in prompt


def test_execute_command_reports_disconnected_without_handler(monkeypatch) -> None:
    import importlib

    import app.services.socket_pool as socket_pool

    input_center_module = importlib.import_module("app.services.socket_pool.input_center")

    class FakeInputSDK:
        def send(self, item_id: str, command: str) -> bool:
            raise AssertionError("send should not be called without a terminal handler")

    monkeypatch.setattr(socket_pool, "InputSDK", FakeInputSDK)
    monkeypatch.setattr(input_center_module.input_center, "has_handler", lambda item_id: False)

    server = LocalMCPServer()
    restore_calls: list[str] = []
    monkeypatch.setattr(
        server,
        "_restore_existing_terminal_input",
        lambda item_id: restore_calls.append(item_id) or False,
    )
    result = server.call_tool(
        "execute_command",
        {
            "item_id": "item-1",
            "command": "echo 23231",
        },
    )

    assert result == [
        {
            "type": "text",
            "text": "终端未连接或未打开，命令没有发送。请先启动或连接终端后再试。",
        }
    ]
    assert restore_calls == ["item-1"]


def test_execute_command_restores_existing_terminal_input_handler(monkeypatch) -> None:
    import importlib

    import app.services.socket_pool as socket_pool

    input_center_module = importlib.import_module("app.services.socket_pool.input_center")

    sent: dict[str, str] = {}
    handler_checks = {"value": 0}
    restore_calls: list[str] = []

    class FakeInputSDK:
        def send(self, item_id: str, command: str) -> bool:
            sent["item_id"] = item_id
            sent["command"] = command
            return True

    def fake_has_handler(item_id: str) -> bool:
        handler_checks["value"] += 1
        return handler_checks["value"] >= 2

    monkeypatch.setattr(socket_pool, "InputSDK", FakeInputSDK)
    monkeypatch.setattr(input_center_module.input_center, "has_handler", fake_has_handler)

    server = LocalMCPServer()
    monkeypatch.setattr(
        server,
        "_restore_existing_terminal_input",
        lambda item_id: restore_calls.append(item_id) or True,
    )

    result = server.call_tool(
        "execute_command",
        {
            "item_id": "item-1",
            "command": "echo restored",
        },
    )

    assert restore_calls == ["item-1"]
    assert sent == {"item_id": "item-1", "command": "echo restored\n"}
    assert result == [
        {
            "type": "text",
            "text": "命令已发送到终端，尚未确认执行结果: echo restored",
        }
    ]


def test_installed_software_tools_record_list_remove(monkeypatch, tmp_path) -> None:
    import app.services.agent.installed_software as installed_software

    monkeypatch.setattr(installed_software, "_INSTALLED_SOFTWARE_DIR", tmp_path)

    server = LocalMCPServer()
    record_result = server.call_tool(
        "record_installed_software",
        {
            "item_id": "item-1",
            "name": "openjdk-21-jdk-headless",
            "manager": "apt",
            "version": "21",
            "command": "apt-get install -y openjdk-21-jdk-headless",
        },
    )
    assert "Recorded installed software" in record_result[0]["text"]

    list_result = server.call_tool("list_installed_software", {"item_id": "item-1"})
    assert "openjdk-21-jdk-headless" in list_result[0]["text"]
    assert "version=21" in list_result[0]["text"]

    remove_result = server.call_tool(
        "remove_installed_software",
        {"item_id": "item-1", "name": "openjdk-21-jdk-headless", "manager": "apt"},
    )
    assert "Removed 1 installed software record" in remove_result[0]["text"]

    empty_result = server.call_tool("list_installed_software", {"item_id": "item-1"})
    assert "none recorded" in empty_result[0]["text"]


def test_chat_prompt_includes_installed_software_list(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    import app.services.agent.installed_software as installed_software
    from app.services.agent.prompts import builder as prompt_builder

    monkeypatch.setattr(installed_software, "_INSTALLED_SOFTWARE_DIR", tmp_path)
    installed_software.record_installed_software(
        "item-1",
        name="openjdk-21-jdk-headless",
        manager="apt",
        version="21",
    )

    agent = SimpleNamespace(
        _context=SimpleNamespace(
            agent_profile={},
            enabled_knowledge_files=[],
            skill_revision=skill_loader.revision,
        ),
        get_skills=lambda: [],
        match_skills=lambda query: [],
        get_mcp_servers=lambda: ["local"],
    )

    messages = prompt_builder.build_chat_turn_messages(
        agent,
        item_id="item-1",
        message="安装 java",
        latest_only_context=True,
    )

    assert "Current installed software list" in messages[0]["content"]
    assert "openjdk-21-jdk-headless" in messages[0]["content"]
    assert "version=21" in messages[0]["content"]

def test_run_job_reports_final_daemon_result(monkeypatch) -> None:
    from types import SimpleNamespace

    server = LocalMCPServer()
    captured: dict[str, object] = {}

    class FakeConnection:
        def run_job_http(self, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "job_id": "job-123",
                "command": kwargs["command"],
                "cwd": "/workspace/item",
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 1.25,
                "output_tail": "download complete\nbuild complete",
            }

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )

    result = server.call_tool(
        "run_job",
        {
            "item_id": "item-1",
            "command": "bun install",
            "timeout_seconds": 12,
            "tail_lines": 5,
            "wait_for_completion": True,
        },
    )

    assert len(result) == 1
    assert result[0]["type"] == "text"
    text = result[0]["text"]
    assert "Job succeeded" in text
    assert "job_id: job-123" in text
    assert "exit_code: 0" in text
    assert "download complete" in text
    assert captured == {
        "item_uuid": "item-1",
        "user_uuid": "user-1",
        "command": "bun install",
        "working_directory": "/workspace/item",
        "timeout_seconds": 12,
        "tail_lines": 5,
    }


def test_run_job_defaults_to_background_and_notifies_session(monkeypatch) -> None:
    import threading
    from types import SimpleNamespace

    from app.services.agent.session import RUN_JOB_TOOL_NAME, agent_session_manager

    item_id = "item-background-job"
    server = LocalMCPServer()
    delivered: list[object] = []
    started = threading.Event()
    allow_finish = threading.Event()
    done = threading.Event()

    class FakeConnection:
        def run_job_http(self, **kwargs):
            started.set()
            assert allow_finish.wait(2)
            return {
                "success": True,
                "job_id": "job-bg",
                "command": kwargs["command"],
                "cwd": "/workspace/item",
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 3.0,
                "output_tail": "install complete",
            }

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )

    agent_session_manager.remove_session(item_id)
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")

    def fake_process_input(input_msg):
        delivered.append(input_msg)
        done.set()

    monkeypatch.setattr(session, "process_input", fake_process_input)
    try:
        result = server.call_tool(
            "run_job",
            {"item_id": item_id, "command": "apt-get install -y temurin-17-jdk"},
        )
        assert started.wait(2)
        assert session.has_running_terminal_job() is True
        allow_finish.set()
        assert done.wait(2)
    finally:
        allow_finish.set()
        agent_session_manager.remove_session(item_id)

    assert "后台任务已启动" in result[0]["text"]
    assert session.has_running_terminal_job() is False
    assert len(delivered) == 1
    assert delivered[0].input_type.value == "terminal"
    assert "Background terminal job completed" in delivered[0].content
    assert "install complete" in delivered[0].content


def test_list_jobs_reports_active_daemon_jobs(monkeypatch) -> None:
    from types import SimpleNamespace

    server = LocalMCPServer()
    captured: dict[str, object] = {}

    class FakeConnection:
        def list_jobs_http(self, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "jobs": [
                    {
                        "job_id": "job-7",
                        "item_uuid": "item-1",
                        "command": "apt-get install -y temurin-17-jdk",
                        "elapsed_seconds": 12.4,
                        "cancel_requested": False,
                    }
                ],
                "count": 1,
            }

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )

    result = server.call_tool("list_jobs", {"item_id": "item-1"})

    assert captured == {"item_uuid": "item-1"}
    assert len(result) == 1
    text = result[0]["text"]
    assert "job_id=job-7" in text
    assert "apt-get install -y temurin-17-jdk" in text


def test_cancel_job_tool_cancels_selected_daemon_job(monkeypatch) -> None:
    from types import SimpleNamespace

    server = LocalMCPServer()
    captured: list[dict[str, object]] = []

    class FakeConnection:
        def cancel_job_http(self, **kwargs):
            captured.append(kwargs)
            return {"success": True, "cancelled": True, "job_id": kwargs["job_id"]}

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )

    result = server.call_tool(
        "cancel_job",
        {"item_id": "item-1", "job_id": "job-7"},
    )

    assert captured == [{"item_uuid": "item-1", "job_id": "job-7"}]
    assert "job-7" in result[0]["text"]


def test_run_job_marks_busy_and_blocks_nested_terminal_commands(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.services.agent.session import agent_session_manager

    item_id = "item-running-job"
    server = LocalMCPServer()
    nested: dict[str, list] = {}

    class FakeConnection:
        def run_job_http(self, **kwargs):
            session = agent_session_manager.get_session(item_id)
            assert session is not None
            assert session.has_running_terminal_job() is True
            nested["execute"] = server.call_tool(
                "execute_command",
                {"item_id": item_id, "command": "java -version"},
            )
            nested["run_job"] = server.call_tool(
                "run_job",
                {"item_id": item_id, "command": "apt update"},
            )
            return {
                "success": True,
                "job_id": "job-running",
                "command": kwargs["command"],
                "cwd": "/workspace/item",
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 2.0,
                "output_tail": "done",
            }

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )

    agent_session_manager.remove_session(item_id)
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")
    try:
        result = server.call_tool(
            "run_job",
            {
                "item_id": item_id,
                "command": "curl https://example.test/file -o file",
                "wait_for_completion": True,
            },
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert "Job succeeded" in result[0]["text"]
    assert "\u540e\u53f0\u4efb\u52a1\u6b63\u5728\u8fd0\u884c" in nested["execute"][0]["text"]
    assert "java -version" not in nested["execute"][0]["text"]
    assert "\u4e0d\u4f1a\u91cd\u590d\u53d1\u9001" in nested["execute"][0]["text"]
    assert "\u540e\u53f0\u4efb\u52a1\u6b63\u5728\u8fd0\u884c" in nested["run_job"][0]["text"]
    assert "apt update" not in nested["run_job"][0]["text"]
    assert "\u4e0d\u4f1a\u91cd\u590d\u53d1\u9001" in nested["run_job"][0]["text"]
    assert session.has_running_terminal_job() is False



def test_interrupt_command_cancels_running_daemon_job(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.services.agent.session import RUN_JOB_TOOL_NAME, agent_session_manager

    item_id = "item-cancel-job"
    server = LocalMCPServer()
    cancelled: list[dict] = []

    class FakeConnection:
        def cancel_job_http(self, **kwargs):
            cancelled.append(kwargs)
            return {"success": True, "cancelled": True, "job_id": "job-1"}

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )

    agent_session_manager.remove_session(item_id)
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")
    session.mark_terminal_job_started(
        RUN_JOB_TOOL_NAME,
        {"item_id": item_id, "command": "apt-get install -y temurin-17-jdk"},
    )
    try:
        result = server.call_tool("interrupt_command", {"item_id": item_id})
    finally:
        agent_session_manager.remove_session(item_id)

    assert cancelled == [{"item_uuid": item_id}]
    assert "\u540e\u53f0\u4efb\u52a1\u5df2\u4e2d\u65ad" in result[0]["text"]
    assert session.has_running_terminal_job() is False


def test_run_job_tool_is_registered_for_long_jobs() -> None:
    server = LocalMCPServer()
    tool = next(tool for tool in server.list_tools() if tool["name"] == "run_job")

    assert "long-running shell job" in tool["description"]
    assert tool["inputSchema"]["properties"]["timeout_seconds"]["default"] == 600
    assert tool["skip_memory"] is True