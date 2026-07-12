import asyncio
import sys
import types
from pathlib import Path

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

from service import socket_service as socket_service_module
from service.socket_service import SocketService


class FakeSio:
    def __init__(self):
        self.emits = []

    async def emit(self, event, data, room=None):
        self.emits.append((event, data, room))


class FakeRoomManager:
    def __init__(self, room_info):
        self.room_info = room_info

    def get_room_info(self, room):
        return self.room_info


def test_broadcast_skips_missing_room(monkeypatch):
    sio = FakeSio()
    service = SocketService(sio)
    monkeypatch.setattr(socket_service_module, "room_manager", FakeRoomManager(None))

    asyncio.run(service.broadcast_to_terminal("missing-item", "stream", {"stdout": "ok"}))

    assert sio.emits == []


def test_broadcast_skips_empty_room(monkeypatch):
    sio = FakeSio()
    service = SocketService(sio)
    monkeypatch.setattr(
        socket_service_module,
        "room_manager",
        FakeRoomManager({"permanent_count": 0, "temporary_count": 0}),
    )

    asyncio.run(service.broadcast_to_terminal("item-1", "stream", {"stdout": "ok"}))

    assert sio.emits == []


def test_broadcast_emits_when_room_has_subscribers(monkeypatch):
    sio = FakeSio()
    service = SocketService(sio)
    monkeypatch.setattr(
        socket_service_module,
        "room_manager",
        FakeRoomManager({"permanent_count": 1, "temporary_count": 0, "permanent": []}),
    )

    asyncio.run(service.broadcast_to_terminal("item-1", "stream", {"stdout": "ok"}))

    assert sio.emits == [("stream", {"stdout": "ok"}, "item-1")]
