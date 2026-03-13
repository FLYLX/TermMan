import socketio
import requests
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
        # API配置
        self.api_base_url = f"{self.config.base_url}/api"
        self.headers = {
            "X-API-Key": self.config.api_key
        }
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
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            self.status = ConnectionStatus.CONNECTING
            logger.debug(f"Attempting to connect to {self.config.base_url} with API key: {self.config.api_key}")
            self.sio.connect(
                self.config.base_url,
                transports=["websocket"],
                auth={"api_key": self.config.api_key}
            )
            return True
        except Exception as e:
            logger.error(f"Connection to {self.config.base_url} failed: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            import traceback
            logger.error(f"Error traceback: {traceback.format_exc()}")
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
    
    def _http_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        发送HTTP GET请求
        """
        try:
            url = f"{self.api_base_url}/{endpoint}"
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _http_post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        发送HTTP POST请求
        """
        try:
            url = f"{self.api_base_url}/{endpoint}"
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def health_check(self) -> bool:
        """
        健康检查
        """
        try:
            url = self.config.base_url
            response = requests.get(url)
            return response.status_code == 200
        except Exception:
            return False
    
    def terminal_start_http(self, user_uuid: str, token: str) -> Dict[str, Any]:
        """
        HTTP方式启动终端
        """
        return self._http_post("terminal/start", {
            "user_uuid": user_uuid,
            "token": token
        })
    
    def terminal_stop_http(self, item_uuid: str) -> Dict[str, Any]:
        """
        HTTP方式停止终端
        """
        return self._http_post("terminal/stop", {
            "item_uuid": item_uuid
        })
    
    def terminal_status_http(self, item_uuid: str) -> Dict[str, Any]:
        """
        HTTP方式获取终端状态
        """
        return self._http_get(f"terminal/status/{item_uuid}")
