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

from core.daemon_conn_pool import BackendMainConnection, BackendRoomListenConnection
from service import socket_service as socket_service_module
from service.socket_service import SocketService


class FakeSio:
    def __init__(self):
        self.emits = []
        self.left_rooms = []

    async def emit(self, event, data, room=None):
        self.emits.append((event, data, room))

    async def leave_room(self, sid, room):
        self.left_rooms.append((sid, room))


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


def test_backend_room_disconnect_removes_permanent_subscriber(monkeypatch):
    sio = FakeSio()
    service = SocketService(sio)
    removed = []

    class DisconnectRoomManager:
        def remove_subscriber(self, room_id, sid):
            removed.append((room_id, sid))

        def get_room_info(self, _room_id):
            return {"permanent_count": 0, "temporary_count": 0}

    class DisconnectConnPool:
        def get_backend_main_conn(self, _api_key):
            return None

        def get_all_backend_room_listen_conns(self):
            return [SimpleNamespace(conn_id="backend-room-sid", item_uuid="item-1")]

        def remove_backend_room_listen_conn(self, item_uuid):
            assert item_uuid == "item-1"

        def get_all_browser_terminal_conns(self):
            return {}

        def get_all_backend_main_conns(self):
            return []

    monkeypatch.setattr(socket_service_module, "room_manager", DisconnectRoomManager())
    monkeypatch.setattr(socket_service_module, "daemon_conn_pool", DisconnectConnPool())

    asyncio.run(service.handle_disconnect("backend-room-sid"))

    assert removed == [("item-1", "backend-room-sid")]
    assert sio.left_rooms == [("backend-room-sid", "item-1")]


def test_socketio_connections_are_live_when_sid_is_registered() -> None:
    main_connection = BackendMainConnection("secret")
    room_connection = BackendRoomListenConnection("item-1")

    main_connection.set_connected(None, "main-sid")
    room_connection.set_connected(None, "room-sid")

    assert main_connection.is_connected() is True
    assert room_connection.is_connected() is True


def test_connection_update_uses_registered_socketio_sid(monkeypatch) -> None:
    emitted = []
    main_connection = BackendMainConnection("secret")
    main_connection.set_connected(None, "main-sid")

    class UpdateSio:
        async def emit(self, event, data, to=None):
            emitted.append((event, data, to))

    class UpdateConnPool:
        def get_all_backend_main_conns(self):
            return [main_connection]

    class UpdateRoomManager:
        def get_room_info(self, item_uuid):
            return {"room_id": item_uuid, "permanent_count": 1, "temporary_count": 0}

    service = SocketService(UpdateSio())
    monkeypatch.setattr(socket_service_module, "daemon_conn_pool", UpdateConnPool())
    monkeypatch.setattr(socket_service_module, "room_manager", UpdateRoomManager())
    monkeypatch.setattr(service, "get_terminal_connections", lambda _item_uuid: {})

    asyncio.run(service.notify_connection_update("item-1"))

    assert emitted[0][0] == "connection_update"
    assert emitted[0][2] == "main-sid"
