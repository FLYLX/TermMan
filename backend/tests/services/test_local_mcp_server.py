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