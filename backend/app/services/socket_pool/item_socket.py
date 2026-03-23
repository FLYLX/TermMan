from typing import Any
import logging
import threading

import socketio

from ..protocol import ProtocolEvents
from .socket_models import TerminalStatus
from .subscription_center import subscription_center

logger = logging.getLogger(__name__)


class ItemSocket:
    """
    代表单个终端的Socket连接 - 按 UPDATE.MD 规范
    
    支持两种订阅者类型：
    1. backend: 永久订阅者，监听输出写日志
    2. browser: 临时订阅者，实时渲染终端
    
    事件流：
    ItemSocket 接收事件 -> 发布到 SubscriptionCenter -> 订阅者收到通知
    """
    def __init__(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str, subscriber_type: str = "browser"):
        self.item_uuid = item_uuid
        self.token = token
        self.daemon_url = daemon_url
        self.user_uuid = user_uuid
        self.subscriber_type = subscriber_type
        self.status = TerminalStatus.STOPPED
        self.sio = socketio.Client(reconnection=False)
        self._connected_event = threading.Event()
        self._connect_error = None
        self.setup_event_handlers()

    def setup_event_handlers(self):
        @self.sio.event
        def connect():
            logger.info(f"[ItemSocket] Socket connect event for item={self.item_uuid}")

        @self.sio.event
        def disconnect():
            self.status = TerminalStatus.STOPPED
            self._connected_event.clear()
            subscription_center.publish_disconnected(self.item_uuid, {"item_uuid": self.item_uuid})

        @self.sio.event
        def terminal_connected(data):
            logger.info(f"[ItemSocket] Terminal connected: {data}")
            self.status = TerminalStatus.RUNNING
            self._connected_event.set()
            subscription_center.publish_connected(self.item_uuid, data)

        @self.sio.event
        def auth_error(data):
            logger.error(f"[ItemSocket] Auth error: {data}")
            self._connect_error = data
            self._connected_event.set()
            subscription_center.publish_auth_error(self.item_uuid, data)

        @self.sio.on(ProtocolEvents.STREAM)
        def on_stream(data):
            stdout = data.get("stdout", "")
            stderr = data.get("stderr", "")
            stdin = data.get("stdin", "")
            
            if stdout:
                logger.debug(f"[ItemSocket] Received stdout for item={self.item_uuid}: {len(stdout)} chars")
            if stderr:
                logger.debug(f"[ItemSocket] Received stderr for item={self.item_uuid}: {len(stderr)} chars")
            if stdin:
                logger.debug(f"[ItemSocket] Received stdin for item={self.item_uuid}: {len(stdin)} chars")
            
            subscription_center.publish_stream(self.item_uuid, data)

    def connect(self, api_key: str, timeout: float = 10.0) -> bool:
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
        try:
            self.sio.disconnect()
        except Exception:
            pass
        self.status = TerminalStatus.STOPPED

    def emit(self, event: str, data: Any) -> bool:
        if self.status != TerminalStatus.RUNNING:
            return False
        try:
            self.sio.emit(event, data)
            return True
        except Exception:
            return False

    def write(self, command: str) -> bool:
        return self.emit(ProtocolEvents.WRITE, {
            "command": command
        })

    def is_connected(self) -> bool:
        return self.status == TerminalStatus.RUNNING

    def get_status(self) -> TerminalStatus:
        return self.status
