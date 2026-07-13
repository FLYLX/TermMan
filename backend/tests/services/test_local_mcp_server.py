from app.services.agent.mcp.local_server import LocalMCPServer
from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.mcp.context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.session import (
    is_background_job_started_result,
    is_tool_result_auto_routed_to_job,
    should_auto_route_terminal_tool_to_job,
)
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


def test_execute_command_auto_routes_busy_command_to_background_job(monkeypatch) -> None:
    import importlib

    import app.services.socket_pool as socket_pool
    from app.services.agent.session import EXECUTE_COMMAND_TOOL_NAME, agent_session_manager

    input_center_module = importlib.import_module("app.services.socket_pool.input_center")
    item_id = "item-auto-route"
    routed: dict[str, object] = {}

    class FakeInputSDK:
        def send(self, item_id: str, command: str) -> bool:
            raise AssertionError("busy command should be routed to run_job, not terminal input")

    def fake_run_job(args: dict):
        routed.update(args)
        return [{"type": "text", "text": "\u540e\u53f0\u4efb\u52a1\u5df2\u542f\u52a8"}]

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

    server = LocalMCPServer()
    monkeypatch.setattr(server, "_run_job", fake_run_job)

    try:
        result = server.call_tool(
            "execute_command",
            {
                "item_id": item_id,
                "command": "python -m pip install requests",
                "timeout_seconds": 20,
            },
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert routed["item_id"] == item_id
    assert routed["command"] == "python -m pip install requests"
    assert routed["timeout_seconds"] == 60
    assert routed["wait_for_completion"] is False
    assert "\u540e\u53f0 Job" in result[0]["text"]
    assert result[1]["type"] == "metadata"
    assert result[1]["auto_routed_execute_command_to_run_job"] is True


def test_execute_command_auto_routes_shell_query_when_console_is_active(
    monkeypatch,
) -> None:
    import importlib

    import app.services.socket_pool as socket_pool
    from app.services.agent.session import EXECUTE_COMMAND_TOOL_NAME, agent_session_manager

    input_center_module = importlib.import_module("app.services.socket_pool.input_center")
    item_id = "item-console-shell-query"
    routed: dict[str, object] = {}

    class FakeInputSDK:
        def send(self, item_id: str, command: str) -> bool:
            raise AssertionError("shell query should be routed to run_job, not console input")

    def fake_run_job(args: dict):
        routed.update(args)
        return [{"type": "text", "text": "\u540e\u53f0\u4efb\u52a1\u5df2\u542f\u52a8"}]

    monkeypatch.setattr(socket_pool, "InputSDK", FakeInputSDK)
    monkeypatch.setattr(input_center_module.input_center, "has_handler", lambda item_id: True)

    agent_session_manager.remove_session(item_id)
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")
    monkeypatch.setattr(session, "_schedule_pending_command_recheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(session, "_get_log_line_count", lambda: 0)
    session.mark_terminal_command_dispatched(
        EXECUTE_COMMAND_TOOL_NAME,
        {"command": "java -jar paper-server.jar nogui"},
    )

    server = LocalMCPServer()
    monkeypatch.setattr(server, "_run_job", fake_run_job)

    try:
        result = server.call_tool(
            "execute_command",
            {
                "item_id": item_id,
                "command": "ls -la",
            },
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert routed["item_id"] == item_id
    assert routed["command"] == "ls -la"
    assert routed["wait_for_completion"] is False
    assert "\u540e\u53f0 Job" in result[0]["text"]
    assert result[1]["type"] == "metadata"
    assert result[1]["auto_routed_execute_command_to_run_job"] is True


def test_execute_command_sends_cd_then_server_launcher_when_console_context_is_stale(
    monkeypatch,
) -> None:
    import importlib

    import app.services.socket_pool as socket_pool
    from app.services.agent.session import EXECUTE_COMMAND_TOOL_NAME, agent_session_manager

    input_center_module = importlib.import_module("app.services.socket_pool.input_center")
    item_id = "item-stale-console-launch"
    sent: dict[str, str] = {}

    class FakeInputSDK:
        def send(self, item_id: str, command: str) -> bool:
            sent["item_id"] = item_id
            sent["command"] = command
            return True

    monkeypatch.setattr(socket_pool, "InputSDK", FakeInputSDK)
    monkeypatch.setattr(input_center_module.input_center, "has_handler", lambda item_id: True)

    agent_session_manager.remove_session(item_id)
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")
    monkeypatch.setattr(session, "_schedule_pending_command_recheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(session, "_get_log_line_count", lambda: 0)
    session.mark_terminal_command_dispatched(
        EXECUTE_COMMAND_TOOL_NAME,
        {"command": "bash run.sh"},
    )

    try:
        result = LocalMCPServer().call_tool(
            "execute_command",
            {
                "item_id": item_id,
                "command": "cd temp_extract && bash run.sh",
            },
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert sent == {
        "item_id": item_id,
        "command": "cd temp_extract && bash run.sh\n",
    }
    assert result[0]["type"] == "text"
    assert "cd temp_extract && bash run.sh" in result[0]["text"]


def test_auto_routed_execute_command_result_skips_pending_terminal_lock() -> None:
    assert should_auto_route_terminal_tool_to_job(
        "mcp_local_execute_command",
        {"command": "python -m pip install requests"},
    ) is True
    assert should_auto_route_terminal_tool_to_job(
        "mcp_local_execute_command",
        {"command": "java -version"},
    ) is False
    assert should_auto_route_terminal_tool_to_job(
        "mcp_local_execute_command",
        {"command": "./run.sh"},
    ) is False
    assert should_auto_route_terminal_tool_to_job(
        "mcp_local_execute_command",
        {
            "command": (
                "java @user_jvm_args.txt "
                "@libraries/net/minecraftforge/forge/1.20.1-47.4.20/unix_args.txt nogui"
            )
        },
    ) is False

    assert is_tool_result_auto_routed_to_job(
        {
            "success": True,
            "result": [
                {"type": "text", "text": "background job started"},
                {
                    "type": "metadata",
                    "auto_routed_execute_command_to_run_job": True,
                },
            ],
        }
    ) is True

    assert is_tool_result_auto_routed_to_job(
        {"success": True, "result": [{"type": "text", "text": "command sent"}]}
    ) is False

    assert is_background_job_started_result(
        {
            "success": True,
            "result": [
                {"type": "text", "text": "background job started"},
                {"type": "metadata", "background_job_started": True},
            ],
        }
    ) is True

    assert is_background_job_started_result(
        {
            "success": True,
            "result": [
                {"type": "text", "text": "background job started"},
                {"type": "metadata", "auto_routed_execute_command_to_run_job": True},
            ],
        }
    ) is True

    assert is_background_job_started_result(
        {"success": True, "result": [{"type": "text", "text": "command sent"}]}
    ) is False

def test_system_prompt_forbids_claiming_command_success_without_confirmation() -> None:
    skill_loader.reload()
    prompt = get_system_prompt()

    assert "不代表命令执行成功" in prompt
    assert "命令已发送，等待终端结果确认" in prompt
    assert "终端防卡死规则" in prompt
    assert "终端打开不等于 shell 空闲" in prompt
    assert "不要为了试探是否可输入而连续发送" in prompt
    assert "不要拼接 shell 命令" in prompt
    assert "先判断命令性质，再选择工具" in prompt
    assert "Minecraft/Forge/Paper/Fabric/类 Minecraft 服务端启动" in prompt
    assert "必须放在主终端前台运行" in prompt
    assert "mcp_local_add_terminal_input_filter_rule" in prompt
    assert "mcp_local_list_terminal_input_filter_rules" in prompt
    assert "mcp_local_delete_terminal_input_filter_rule" in prompt
    assert "mcp_local_clear_terminal_input_filter_rules" in prompt
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


def test_terminal_input_filter_rule_tool_adds_noise_block_rule(db) -> None:
    from app.models import Item
    from app.services.filters.input_filter import InputFilter, InputFilterConfig
    from tests.utils.item import create_random_item

    item = create_random_item(db)
    server = LocalMCPServer()

    result = server.call_tool(
        "add_terminal_input_filter_rule",
        {
            "item_id": str(item.id),
            "name": "noise_ftb_backups",
            "regex_patterns": [
                r"FTBBackups/]: Attempting to create an automatic backup"
            ],
            "reason": "Repeated automatic backup status line.",
        },
    )

    assert "Added terminal output -> Agent input filter rule" in result[0]["text"]
    updated = db.get(Item, item.id)
    assert updated is not None
    db.refresh(updated)
    assert updated.input_filter_enabled is True
    assert "noise_ftb_backups" in updated.input_filter_rules

    input_filter = InputFilter(InputFilterConfig.from_item(updated))
    filtered = input_filter.filter(
        {
            "stdout": (
                "[22:00:00] [ftbbackups2_Worker-1/INFO] "
                "[ne.cr.ft.FTBBackups/]: "
                "Attempting to create an automatic backup\n"
            ),
            "stderr": "",
        }
    )
    assert filtered is None

    list_result = server.call_tool(
        "list_terminal_input_filter_rules",
        {"item_id": str(item.id)},
    )
    assert "noise_ftb_backups" in list_result[0]["text"]
    assert "FTBBackups" in list_result[0]["text"]


def test_terminal_filter_rule_tool_lists_input_and_output_rules(db) -> None:
    from tests.utils.item import create_random_item

    item = create_random_item(db)
    item.input_filter_enabled = True
    item.input_filter_rules = {
        "noise_backup": {
            "regex_patterns": [r"Attempting to create an automatic backup"],
            "action_type": "block",
            "reason": "Repeated backup line.",
        }
    }
    item.output_filter_enabled = True
    item.output_filter_rules = {
        "dangerous_rm": {
            "regex_patterns": [r"rm\s+-rf\s+/"],
            "action_type": "block",
            "reason": "Protect root filesystem.",
        }
    }
    db.add(item)
    db.commit()

    server = LocalMCPServer()
    result = server.call_tool(
        "list_terminal_filter_rules",
        {"item_id": str(item.id)},
    )

    text = result[0]["text"]
    assert "Input filter (terminal output -> Agent) enabled=True; rules=1" in text
    assert "noise_backup" in text
    assert "Attempting to create an automatic backup" in text
    assert "Output filter (Agent command -> terminal) enabled=True; rules=1" in text
    assert "dangerous_rm" in text
    assert r"rm\s+-rf\s+/" in text


def test_terminal_input_filter_rule_tools_delete_and_clear_rules(db) -> None:
    from app.models import Item
    from tests.utils.item import create_random_item

    item = create_random_item(db)
    server = LocalMCPServer()

    server.call_tool(
        "add_terminal_input_filter_rule",
        {
            "item_id": str(item.id),
            "name": "noise_one",
            "regex_patterns": [r"noise one"],
        },
    )
    server.call_tool(
        "add_terminal_input_filter_rule",
        {
            "item_id": str(item.id),
            "name": "noise_two",
            "regex_patterns": [r"noise two"],
        },
    )

    delete_result = server.call_tool(
        "delete_terminal_input_filter_rule",
        {"item_id": str(item.id), "name": "noise_one"},
    )
    assert "Deleted terminal output -> Agent input filter rule `noise_one`" in delete_result[0]["text"]

    updated = db.get(Item, item.id)
    assert updated is not None
    db.refresh(updated)
    assert "noise_one" not in updated.input_filter_rules
    assert "noise_two" in updated.input_filter_rules
    assert updated.input_filter_enabled is True

    clear_result = server.call_tool(
        "clear_terminal_input_filter_rules",
        {"item_id": str(item.id)},
    )
    assert "Cleared terminal output -> Agent input filter rules" in clear_result[0]["text"]

    db.refresh(updated)
    assert updated.input_filter_rules == {}
    assert updated.input_filter_enabled is False


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


def test_tool_descriptions_guide_foreground_background_command_choice() -> None:
    server = LocalMCPServer()

    execute_tool = next(tool for tool in server.list_tools() if tool["name"] == "execute_command")
    run_job_tool = next(tool for tool in server.list_tools() if tool["name"] == "run_job")

    assert "主终端前台" in execute_tool["description"]
    assert "Minecraft/Forge/Paper/Fabric" in execute_tool["description"]
    assert "run.sh/start.sh" in execute_tool["description"]
    assert "op/say/stop" in execute_tool["description"]
    assert "stdin closed" in run_job_tool["description"]
    assert (
        "Before using it, decide whether the command needs an interactive foreground console"
        in run_job_tool["description"]
    )
    assert (
        "Do not choose run_job for Minecraft/Forge/Paper/Fabric server startup"
        in run_job_tool["description"]
    )
    assert "choose execute_command in the main terminal" in run_job_tool["description"]
    assert "shell inspection commands" in run_job_tool["description"]


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
    assert result[1]["type"] == "metadata"
    assert result[1]["background_job_started"] is True
    assert session.has_running_terminal_job() is False
    assert len(delivered) == 1
    assert delivered[0].input_type.value == "terminal"
    assert "Background terminal job completed" in delivered[0].content
    assert "install complete" in delivered[0].content


def test_background_run_job_queues_robot_completion(monkeypatch) -> None:
    import threading
    from types import SimpleNamespace

    from app.plugins.robot.service import robot_service

    item_id = "item-background-job-robot"
    server = LocalMCPServer()
    queued: list[dict] = []
    started = threading.Event()
    done = threading.Event()
    target = RobotReplyTarget(
        target_type="private",
        target_id="2537134688",
        metadata={"mentioned_bot": True},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="00000000-0000-0000-0000-000000000001",
            sender_key="2537134688",
            reply_target=target,
            conversation_key="private:2537134688",
            conversation_generation=7,
            reply_requires_awake=True,
        )
    )

    class FakeConnection:
        def run_job_http(self, **kwargs):
            started.set()
            return {
                "success": True,
                "job_id": "job-bg-robot",
                "command": kwargs["command"],
                "cwd": "/workspace/item",
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 3.0,
                "output_tail": "temurin installed",
            }

    def fake_enqueue_background_job_result(**kwargs):
        queued.append(kwargs)
        done.set()
        return True

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )
    monkeypatch.setattr(
        robot_service,
        "enqueue_background_job_result",
        fake_enqueue_background_job_result,
    )

    try:
        result = server.call_tool(
            "run_job",
            {
                "item_id": item_id,
                "command": "apt-get install -y temurin-17-jdk",
                "_robot_context_token": token,
            },
        )
        assert started.wait(2)
        assert done.wait(2)
    finally:
        unregister_robot_mcp_context(token)

    assert "后台" in result[0]["text"] or "鍚庡彴" in result[0]["text"]
    assert len(queued) == 1
    assert queued[0]["robot_id"] == "00000000-0000-0000-0000-000000000001"
    assert queued[0]["item_id"] == item_id
    assert queued[0]["sender_key"] == "2537134688"
    assert queued[0]["conversation_key"] == "private:2537134688"
    assert queued[0]["conversation_generation"] == 7
    assert queued[0]["reply_target"]["target_id"] == "2537134688"
    assert "temurin installed" in queued[0]["message"]


def test_background_run_job_delivers_via_reply_ticket_without_robot_queue(
    monkeypatch,
) -> None:
    import threading
    from types import SimpleNamespace

    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.conversation_memory import robot_conversation_memory
    from app.plugins.robot.service import robot_service
    from app.services.agent.reply_ticket import reply_ticket_manager

    item_id = "item-background-job-ticket"
    server = LocalMCPServer()
    started = threading.Event()
    delivered = threading.Event()
    cleared: list[str] = []
    sent: list[tuple[str, RobotReplyTarget, str]] = []
    memory_writes: list[tuple[str, str, str]] = []
    target = RobotReplyTarget(
        target_type="private",
        target_id="2537134688",
        metadata={"conversation": {"type": "private", "id": "2537134688"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="00000000-0000-0000-0000-000000000001",
            sender_key="2537134688",
            reply_target=target,
            conversation_key="private:2537134688",
            conversation_generation=8,
            reply_requires_awake=True,
        )
    )
    fake_agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="00000000-0000-0000-0000-000000000001",
            robot_context_token=token,
            reply_ticket_id="",
        )
    )

    class FakeConnection:
        def run_job_http(self, **kwargs):
            started.set()
            return {
                "success": True,
                "job_id": "job-bg-ticket",
                "command": kwargs["command"],
                "cwd": "/workspace/item",
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 2.5,
                "output_tail": "temurin installed",
            }

    monkeypatch.setattr(
        server,
        "_get_item_daemon_context",
        lambda item_id: (
            SimpleNamespace(owner_id="user-1", working_directory="/workspace/item"),
            FakeConnection(),
        ),
    )
    monkeypatch.setattr(
        robot_service,
        "register_background_job_reply",
        lambda **_kwargs: "pending-ticket-1",
    )
    monkeypatch.setattr(
        robot_service,
        "clear_background_job_reply",
        lambda **kwargs: cleared.append(kwargs["pending_reply_id"]),
    )
    monkeypatch.setattr(
        robot_service,
        "enqueue_background_job_result",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("reply ticket delivery should bypass old robot queue")
        ),
    )
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda robot_id, target, text: (
            sent.append((str(robot_id), target, text)),
            delivered.set(),
        ),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda robot_id, conversation_key, text: memory_writes.append(
            (str(robot_id), conversation_key, text)
        ),
    )

    reply_ticket_manager.reset()
    try:
        ticket = reply_ticket_manager.create_for_agent(
            fake_agent,
            item_id=item_id,
            handler_id="handler-1",
            message="安装 temurin java17",
        )
        result = server.call_tool(
            "run_job",
            {
                "item_id": item_id,
                "command": "apt-get install -y temurin-17-jdk",
                "_robot_context_token": token,
                "_reply_ticket_id": ticket.ticket_id,
            },
        )
        assert started.wait(2)
        assert delivered.wait(2)
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()

    assert "后台任务已启动" in result[0]["text"]
    assert cleared == ["pending-ticket-1"]
    assert [(robot_id, target.target_type, target.target_id) for robot_id, target, _ in sent] == [
        ("00000000-0000-0000-0000-000000000001", "private", "2537134688")
    ]
    assert "后台任务完成了" in sent[0][2]
    assert "apt-get install -y temurin-17-jdk" in sent[0][2]
    assert memory_writes == [
        (
            "00000000-0000-0000-0000-000000000001",
            "private:2537134688",
            sent[0][2],
        )
    ]


def test_background_run_job_passes_web_reply_ticket_to_terminal_feedback(
    monkeypatch,
) -> None:
    import threading
    from types import SimpleNamespace

    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.session import agent_session_manager

    item_id = "item-background-job-web-ticket"
    server = LocalMCPServer()
    started = threading.Event()
    delivered = threading.Event()
    processed_inputs: list[object] = []

    class FakeConnection:
        def run_job_http(self, **kwargs):
            started.set()
            return {
                "success": False,
                "error": "daemon job failed",
                "job_id": "job-web-ticket",
                "command": kwargs["command"],
                "cwd": "/workspace/item",
                "exit_code": 127,
                "timed_out": False,
                "duration_seconds": 0.02,
                "output_tail": "/bin/sh: 1: java: not found",
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
        processed_inputs.append(input_msg)
        delivered.set()

    monkeypatch.setattr(session, "process_input", fake_process_input)
    fake_agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_context_token="",
            reply_ticket_id="",
        )
    )

    reply_ticket_manager.reset()
    try:
        ticket = reply_ticket_manager.create_for_agent(
            fake_agent,
            item_id=item_id,
            handler_id="handler-1",
            message="java 还在不",
        )
        result = server.call_tool(
            "run_job",
            {
                "item_id": item_id,
                "command": "java -version 2>&1",
                "_reply_ticket_id": ticket.ticket_id,
            },
        )
        assert started.wait(2)
        assert delivered.wait(2)
    finally:
        agent_session_manager.remove_session(item_id)
        reply_ticket_manager.reset()

    assert result[0]["type"] == "text"
    assert len(processed_inputs) == 1
    assert processed_inputs[0].reply_ticket_id == ticket.ticket_id
    assert processed_inputs[0].content.startswith("[Background terminal job failed]")


def test_web_reply_ticket_blocks_robot_send_for_terminal_feedback() -> None:
    from types import SimpleNamespace

    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.session import agent_session_manager

    item_id = "item-web-ticket-blocks-qq"
    session = agent_session_manager.get_or_create_session(item_id, "handler-1")
    fake_agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_context_token="",
            reply_ticket_id="",
        )
    )

    reply_ticket_manager.reset()
    try:
        ticket = reply_ticket_manager.create_for_agent(
            fake_agent,
            item_id=item_id,
            handler_id="handler-1",
            message="java 还在不",
        )

        warning = session._robot_send_blocked_by_reply_ticket(
            ticket.ticket_id,
            "mcp_robot_send_message",
        )
        prompt = session._build_reply_ticket_prompt(ticket.ticket_id)
    finally:
        agent_session_manager.remove_session(item_id)
        reply_ticket_manager.reset()

    assert "QQ" in warning
    assert "TermMan web chat" in warning
    assert "do not call QQ tools" in prompt


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
                        "output_tail": "Reading package lists...\nInstalling temurin-17-jdk",
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
    assert "Installing temurin-17-jdk" in text


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
    assert "终端未连接或未打开" in nested["execute"][0]["text"]
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

    assert "non-interactive one-shot shell job" in tool["description"]
    assert tool["inputSchema"]["properties"]["timeout_seconds"]["default"] == 600
    assert tool["skip_memory"] is True
