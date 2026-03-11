import socketio
from typing import Callable, Dict, Any, Optional
from datetime import datetime
from ..protocol import ProtocolEvents, ProtocolCodec
from .connection_models import ConnectionStatus, DaemonConfig


class DaemonConnection:
    """
    单个Daemon节点的TCP连接封装
    """
    def __init__(self, config: DaemonConfig):
        self.config = config
        self.status = ConnectionStatus.DISCONNECTED
        self.sio = socketio.Client()
        self.last_heartbeat = None
        self.callbacks: Dict[str, Callable] = {}
        self.setup_event_handlers()

    def setup_event_handlers(self):
        """
        设置Socket.IO事件处理器
        """
        @self.sio.event
        def connect():
            self.status = ConnectionStatus.CONNECTED
            self.last_heartbeat = datetime.now()
            if "connect" in self.callbacks:
                self.callbacks["connect"]()

        @self.sio.event
        def disconnect():
            self.status = ConnectionStatus.DISCONNECTED
            if "disconnect" in self.callbacks:
                self.callbacks["disconnect"]()

        @self.sio.event
        def heartbeat():
            self.last_heartbeat = datetime.now()
            self.sio.emit("heartbeat_ack")

        @self.sio.on(ProtocolEvents.INSTANCE_STDOUT)
        def on_instance_stdout(data):
            if ProtocolEvents.INSTANCE_STDOUT in self.callbacks:
                self.callbacks[ProtocolEvents.INSTANCE_STDOUT](data)

    def connect(self) -> bool:
        """
        建立与Daemon的连接
        """
        try:
            self.status = ConnectionStatus.CONNECTING
            self.sio.connect(
                self.config.base_url,
                transports=["websocket"],
                auth={"api_key": self.config.api_key}
            )
            return True
        except Exception as e:
            self.status = ConnectionStatus.ERROR
            return False

    def disconnect(self):
        """
        断开与Daemon的连接
        """
        try:
            self.sio.disconnect()
        except Exception:
            pass
        self.status = ConnectionStatus.DISCONNECTED

    def emit(self, event: str, data: Any) -> bool:
        """
        发送事件到Daemon
        """
        if self.status != ConnectionStatus.CONNECTED:
            return False
        try:
            self.sio.emit(event, data)
            return True
        except Exception:
            return False

    def on(self, event: str, callback: Callable):
        """
        注册事件回调
        """
        self.callbacks[event] = callback

    def is_connected(self) -> bool:
        """
        检查连接是否活跃
        """
        return self.status == ConnectionStatus.CONNECTED

    def get_status(self) -> ConnectionStatus:
        """
        获取当前连接状态
        """
        return self.status
