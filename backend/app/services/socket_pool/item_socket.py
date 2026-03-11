import socketio
from typing import Callable, Dict, Any, Optional
from datetime import datetime
from ..protocol import ProtocolEvents, ProtocolCodec
from .socket_models import TerminalStatus, TokenInfo


class ItemSocket:
    """
    单个Item终端的Socket客户端封装
    """
    def __init__(self, item_uuid: str, token: str, daemon_url: str):
        self.item_uuid = item_uuid
        self.token = token
        self.daemon_url = daemon_url
        self.status = TerminalStatus.STOPPED
        self.sio = socketio.Client()
        self.callbacks: Dict[str, Callable] = {}
        self.setup_event_handlers()

    def setup_event_handlers(self):
        """
        设置Socket.IO事件处理器
        """
        @self.sio.event
        def connect():
            self.status = TerminalStatus.RUNNING
            if "connect" in self.callbacks:
                self.callbacks["connect"]()

        @self.sio.event
        def disconnect():
            self.status = TerminalStatus.STOPPED
            if "disconnect" in self.callbacks:
                self.callbacks["disconnect"]()

        @self.sio.on(ProtocolEvents.STREAM)
        def on_stream(data):
            if ProtocolEvents.STREAM in self.callbacks:
                self.callbacks[ProtocolEvents.STREAM](data)

    def connect(self) -> bool:
        """
        建立与终端Socket服务器的连接
        """
        try:
            self.status = TerminalStatus.STARTING
            self.sio.connect(
                self.daemon_url,
                transports=["websocket"],
                auth={"token": self.token, "item_uuid": self.item_uuid}
            )
            return True
        except Exception as e:
            self.status = TerminalStatus.ERROR
            return False

    def disconnect(self):
        """
        断开与终端Socket服务器的连接
        """
        try:
            self.sio.disconnect()
        except Exception:
            pass
        self.status = TerminalStatus.STOPPED

    def emit(self, event: str, data: Any) -> bool:
        """
        发送事件到终端Socket服务器
        """
        if self.status != TerminalStatus.RUNNING:
            return False
        try:
            self.sio.emit(event, data)
            return True
        except Exception:
            return False

    def write(self, command: str) -> bool:
        """
        向终端写入命令
        """
        return self.emit(ProtocolEvents.WRITE, {
            "item_uuid": self.item_uuid,
            "data": command
        })

    def on(self, event: str, callback: Callable):
        """
        注册事件回调
        """
        self.callbacks[event] = callback

    def is_connected(self) -> bool:
        """
        检查连接是否活跃
        """
        return self.status == TerminalStatus.RUNNING

    def get_status(self) -> TerminalStatus:
        """
        获取当前状态
        """
        return self.status
