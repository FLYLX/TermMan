from collections.abc import Callable
from typing import Any
import logging
import threading

import socketio

from ..protocol import ProtocolEvents
from .socket_models import TerminalStatus

logger = logging.getLogger(__name__)


class ItemSocket:
    """
    代表单个终端的Socket连接 - 按 UPDATE.MD 规范
    
    支持两种订阅者类型：
    1. backend: 永久订阅者，监听输出写日志
    2. browser: 临时订阅者，实时渲染终端
    """
    def __init__(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str, subscriber_type: str = "browser"):
        self.item_uuid = item_uuid
        self.token = token
        self.daemon_url = daemon_url
        self.user_uuid = user_uuid
        self.subscriber_type = subscriber_type  # "backend" or "browser"
        self.status = TerminalStatus.STOPPED
        self.callbacks = {}
        self.sio = socketio.Client(reconnection=False)
        self._connected_event = threading.Event()
        self._connect_error = None
        self.setup_event_handlers()

    def setup_event_handlers(self):
        """
        设置Socket.IO事件处理器
        """
        @self.sio.event
        def connect():
            logger.info(f"[ItemSocket] Socket connect event for item={self.item_uuid}")

        @self.sio.event
        def disconnect():
            self.status = TerminalStatus.STOPPED
            self._connected_event.clear()
            if "disconnect" in self.callbacks:
                self.callbacks["disconnect"]()

        @self.sio.event
        def terminal_connected(data):
            logger.info(f"[ItemSocket] Terminal connected: {data}")
            self.status = TerminalStatus.RUNNING
            self._connected_event.set()
            if "terminal_connected" in self.callbacks:
                self.callbacks["terminal_connected"](data)

        @self.sio.event
        def auth_error(data):
            logger.error(f"[ItemSocket] Auth error: {data}")
            self._connect_error = data
            self._connected_event.set()
            if "auth_error" in self.callbacks:
                self.callbacks["auth_error"](data)

        @self.sio.on(ProtocolEvents.STREAM)
        def on_stream(data):
            logger.info(f"[ItemSocket] *** STREAM EVENT RECEIVED *** for item={self.item_uuid}")
            stdout = data.get("stdout", "")
            stderr = data.get("stderr", "")
            stdin = data.get("stdin", "")
            if stdout:
                logger.info(f"[ItemSocket] Received stdout for item={self.item_uuid}:\n{stdout.rstrip()}")
            if stderr:
                logger.info(f"[ItemSocket] Received stderr for item={self.item_uuid}:\n{stderr.rstrip()}")
            if stdin:
                logger.info(f"[ItemSocket] Received stdin for item={self.item_uuid}:\n{stdin.rstrip()}")
            if ProtocolEvents.STREAM in self.callbacks:
                logger.info(f"[ItemSocket] Calling stream callback for item={self.item_uuid}")
                self.callbacks[ProtocolEvents.STREAM](data)
            else:
                logger.warning(f"[ItemSocket] No callback registered for stream event, callbacks={list(self.callbacks.keys())}")

    def connect(self, api_key: str, timeout: float = 10.0) -> bool:
        """
        建立与终端Socket服务器的连接（阻塞等待连接确认）
        
        Args:
            api_key: API密钥
            timeout: 等待连接确认的超时时间（秒）
        
        Returns:
            bool: 连接是否成功
        """
        try:
            self._connected_event.clear()
            self._connect_error = None
            self.status = TerminalStatus.STARTING
            
            logger.info(f"[ItemSocket] Connecting to {self.daemon_url} for item {self.item_uuid}, user {self.user_uuid}, type {self.subscriber_type}")
            
            self.sio.connect(
                self.daemon_url,
                transports=["websocket"],
                auth={"api_key": api_key},
                wait=True,
                wait_timeout=timeout
            )

            logger.info(f"[ItemSocket] Socket connected, emitting terminal_connect")
            
            self.sio.emit(ProtocolEvents.TERMINAL_CONNECT, {
                "item_uuid": self.item_uuid,
                "token": self.token,
                "user_uuid": self.user_uuid,
                "subscriber_type": self.subscriber_type
            })
            
            logger.info(f"[ItemSocket] Waiting for terminal_connected event (timeout={timeout}s)")
            
            if self._connected_event.wait(timeout=timeout):
                if self._connect_error:
                    logger.error(f"[ItemSocket] Connection rejected: {self._connect_error}")
                    self.status = TerminalStatus.ERROR
                    return False
                logger.info(f"[ItemSocket] Connection confirmed for item={self.item_uuid}")
                return True
            else:
                logger.error(f"[ItemSocket] Connection timeout waiting for terminal_connected")
                self.status = TerminalStatus.ERROR
                return False

        except Exception as e:
            logger.error(f"[ItemSocket] Failed to connect: {str(e)}")
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
            "command": command
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
