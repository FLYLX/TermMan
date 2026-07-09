import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if sys.platform == "win32":
    fake_pty = types.ModuleType("pty")
    fake_pty.fork = lambda: (_ for _ in ()).throw(NotImplementedError("pty is not available on Windows"))
    sys.modules.setdefault("pty", fake_pty)

    fake_fcntl = types.ModuleType("fcntl")
    fake_fcntl.ioctl = lambda *args, **kwargs: 0
    sys.modules.setdefault("fcntl", fake_fcntl)

    fake_termios = types.ModuleType("termios")
    fake_termios.TIOCSWINSZ = 0
    fake_termios.TIOCGWINSZ = 0
    sys.modules.setdefault("termios", fake_termios)

sys.path.append(str(Path(__file__).resolve().parent / "src"))

from api import socket_routes


class FakeDaemonConnPool:
    def get_all_browser_terminal_conns(self):
        return {"item-1": [SimpleNamespace(sid="browser-sid")]}

    def get_all_backend_room_listen_conns(self):
        return []


class FakeTerminal:
    def __init__(self):
        self.writes = []

    def write(self, command):
        self.writes.append(command)
        return True


class FakeTerminalManager:
    def __init__(self, terminal):
        self.terminal = terminal

    def get_terminal(self, item_uuid):
        assert item_uuid == "item-1"
        return self.terminal


class FakeSocketService:
    def __init__(self):
        self.broadcasts = []

    def sync_broadcast(self, item_uuid, event, data):
        self.broadcasts.append((item_uuid, event, data))


def test_browser_terminal_write_broadcasts_stdin(monkeypatch):
    terminal = FakeTerminal()
    socket_service = FakeSocketService()

    monkeypatch.setattr(socket_routes, "daemon_conn_pool", FakeDaemonConnPool())
    monkeypatch.setattr(socket_routes, "terminal_manager", FakeTerminalManager(terminal))
    monkeypatch.setattr(socket_routes, "socket_service", socket_service)

    asyncio.run(socket_routes.on_terminal_write("browser-sid", {"command": "ls"}))

    assert terminal.writes == ["ls\n"]
    assert socket_service.broadcasts == [
        (
            "item-1",
            "stream",
            {
                "stdin": "ls\n",
                "stdout": "",
                "stderr": "",
                "source": "browser",
            },
        )
    ]


def test_internal_job_run_route_delegates_to_job_runner(monkeypatch):
    from api import http_routes

    captured = {}

    class FakeJobRunner:
        def run_job(self, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "job_id": "job-1",
                "exit_code": 0,
                "output_tail": "done",
            }

    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())

    payload = http_routes.InternalJobRunRequest(
        user_uuid="user-1",
        command="echo done",
        working_directory="workdir",
        timeout_seconds=30,
        tail_lines=7,
        env={"A": "B"},
    )
    result = http_routes.run_item_job("item-1", payload, _api_key="ok")

    assert result["success"] is True
    assert result["output_tail"] == "done"
    assert captured == {
        "user_uuid": "user-1",
        "item_uuid": "item-1",
        "command": "echo done",
        "working_directory": "workdir",
        "timeout_seconds": 30,
        "tail_lines": 7,
        "env": {"A": "B"},
    }