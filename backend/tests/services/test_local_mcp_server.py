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


def test_system_prompt_forbids_claiming_command_success_without_confirmation() -> None:
    skill_loader.reload()
    prompt = get_system_prompt()

    assert "不代表命令已经执行成功" in prompt
    assert "命令已发送，等待终端结果确认" in prompt


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