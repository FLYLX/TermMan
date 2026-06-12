import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

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
