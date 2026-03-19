import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class DaemonConfig:
    def __init__(self, ip: str, port: int, api_key: str):
        self.ip = ip
        self.port = port
        self.api_key = api_key
        self.daemon_id = f"{ip}:{port}:{api_key}"
        self.base_url = f"http://{ip}:{port}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "daemon_id": self.daemon_id,
            "ip": self.ip,
            "port": self.port,
            "base_url": self.base_url
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DaemonConfig":
        return cls(
            ip=data["ip"],
            port=data["port"],
            api_key=data["api_key"]
        )


class RoomListenConnection:
    """
    Room监听连接 - Backend作为永久订阅者监听Item输出
    
    按 pool.md 规范实现
    """
    def __init__(self, item_uuid: str, daemon_api_key: str):
        self.item_uuid = item_uuid
        self.daemon_api_key = daemon_api_key
        self.room_id = item_uuid
        self.conn: Optional[Any] = None
        self.conn_id: Optional[str] = None
        self.status = ConnectionStatus.DISCONNECTED
        self.last_heartbeat: Optional[float] = None
        self.create_time: float = datetime.now().timestamp()
        self.reconnect_times = 0
        self.max_reconnect_times = 5
        self.reconnect_interval = 3
        self.cache_output: List[Dict[str, Any]] = []
        self.cache_max_size = 1000
        self.callbacks: Dict[str, Any] = {}
        self.lock = threading.Lock()

    def set_connected(self, conn: Any, conn_id: str):
        with self.lock:
            self.conn = conn
            self.conn_id = conn_id
            self.status = ConnectionStatus.CONNECTED
            self.last_heartbeat = datetime.now().timestamp()
            self.reconnect_times = 0

    def set_disconnected(self):
        with self.lock:
            self.status = ConnectionStatus.DISCONNECTED
            self.conn = None

    def set_reconnecting(self):
        with self.lock:
            self.status = ConnectionStatus.RECONNECTING
            self.reconnect_times += 1

    def can_reconnect(self) -> bool:
        with self.lock:
            return self.reconnect_times < self.max_reconnect_times

    def add_to_cache(self, output: Dict[str, Any]):
        with self.lock:
            self.cache_output.append(output)
            if len(self.cache_output) > self.cache_max_size:
                self.cache_output = self.cache_output[-self.cache_max_size:]

    def get_and_clear_cache(self) -> List[Dict[str, Any]]:
        with self.lock:
            cache = self.cache_output.copy()
            self.cache_output = []
            return cache

    def update_heartbeat(self):
        with self.lock:
            self.last_heartbeat = datetime.now().timestamp()

    def is_connected(self) -> bool:
        with self.lock:
            return self.status == ConnectionStatus.CONNECTED and self.conn is not None

    def get_status(self) -> ConnectionStatus:
        with self.lock:
            return self.status

    def register_callback(self, event: str, callback: Any):
        with self.lock:
            self.callbacks[event] = callback

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "item_uuid": self.item_uuid,
                "daemon_api_key": self.daemon_api_key,
                "room_id": self.room_id,
                "conn_id": self.conn_id,
                "status": self.status.value,
                "last_heartbeat": self.last_heartbeat,
                "create_time": self.create_time,
                "reconnect_times": self.reconnect_times,
                "cache_size": len(self.cache_output)
            }


class DaemonMainConnState:
    """
    Daemon主连接状态追踪 - 辅助追踪Daemon主连接状态
    
    按 pool.md 规范实现
    """
    def __init__(self, daemon_api_key: str, ws_main_url: str):
        self.daemon_api_key = daemon_api_key
        self.ws_main_url = ws_main_url
        self.conn_status = ConnectionStatus.DISCONNECTED
        self.last_heartbeat: Optional[float] = None
        self.last_reconnect_time: Optional[float] = None
        self.lock = threading.Lock()

    def set_connected(self):
        with self.lock:
            self.conn_status = ConnectionStatus.CONNECTED
            self.last_heartbeat = datetime.now().timestamp()

    def set_disconnected(self):
        with self.lock:
            self.conn_status = ConnectionStatus.DISCONNECTED

    def update_heartbeat(self):
        with self.lock:
            self.last_heartbeat = datetime.now().timestamp()

    def is_connected(self) -> bool:
        with self.lock:
            return self.conn_status == ConnectionStatus.CONNECTED

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "daemon_api_key": self.daemon_api_key,
                "ws_main_url": self.ws_main_url,
                "conn_status": self.conn_status.value,
                "last_heartbeat": self.last_heartbeat,
                "last_reconnect_time": self.last_reconnect_time
            }


class BackendConnPool:
    """
    Backend全局连接池（单例 + 线程锁）
    
    按 pool.md 规范实现：
    1. room_listen_conn_pool: Room监听连接池（Backend → Daemon Room）
    2. daemon_main_conn_state: Daemon主连接状态追踪（Daemon → Backend）
    
    核心原则：
    - Backend 连接池：仅管理「主动向外的连接」（如监听 Daemon Room 的 WebSocket 连接）
    - 被动接收的连接（浏览器 HTTP/WebSocket、Daemon 主连接）无需池化
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.room_listen_conn_pool: Dict[str, RoomListenConnection] = {}
                cls._instance.daemon_main_conn_state: Dict[str, DaemonMainConnState] = {}
                cls._instance._pool_lock = threading.Lock()
            return cls._instance

    def create_room_listen_conn(self, item_uuid: str, daemon_api_key: str) -> RoomListenConnection:
        with self._pool_lock:
            if item_uuid in self.room_listen_conn_pool:
                return self.room_listen_conn_pool[item_uuid]
            
            conn = RoomListenConnection(item_uuid, daemon_api_key)
            self.room_listen_conn_pool[item_uuid] = conn
            self._log_pool_state(f"Created RoomListenConnection for item={item_uuid}")
            return conn

    def get_room_listen_conn(self, item_uuid: str) -> Optional[RoomListenConnection]:
        with self._pool_lock:
            return self.room_listen_conn_pool.get(item_uuid)

    def remove_room_listen_conn(self, item_uuid: str) -> Optional[RoomListenConnection]:
        with self._pool_lock:
            conn = self.room_listen_conn_pool.pop(item_uuid, None)
            if conn:
                self._log_pool_state(f"Removed RoomListenConnection for item={item_uuid}")
            return conn

    def get_all_room_listen_conns(self) -> List[RoomListenConnection]:
        with self._pool_lock:
            return list(self.room_listen_conn_pool.values())

    def get_connected_room_listen_conns(self) -> List[RoomListenConnection]:
        with self._pool_lock:
            return [conn for conn in self.room_listen_conn_pool.values() if conn.is_connected()]

    def create_daemon_main_conn_state(self, daemon_api_key: str, ws_main_url: str) -> DaemonMainConnState:
        with self._pool_lock:
            if daemon_api_key in self.daemon_main_conn_state:
                return self.daemon_main_conn_state[daemon_api_key]
            
            state = DaemonMainConnState(daemon_api_key, ws_main_url)
            self.daemon_main_conn_state[daemon_api_key] = state
            self._log_pool_state(f"Created DaemonMainConnState for daemon={daemon_api_key[:16]}...")
            return state

    def get_daemon_main_conn_state(self, daemon_api_key: str) -> Optional[DaemonMainConnState]:
        with self._pool_lock:
            return self.daemon_main_conn_state.get(daemon_api_key)

    def remove_daemon_main_conn_state(self, daemon_api_key: str) -> Optional[DaemonMainConnState]:
        with self._pool_lock:
            state = self.daemon_main_conn_state.pop(daemon_api_key, None)
            if state:
                self._log_pool_state(f"Removed DaemonMainConnState for daemon={daemon_api_key[:16]}...")
            return state

    def get_all_daemon_main_conn_states(self) -> List[DaemonMainConnState]:
        with self._pool_lock:
            return list(self.daemon_main_conn_state.values())

    def get_pool_state(self) -> Dict[str, Any]:
        with self._pool_lock:
            return {
                "room_listen_conn_pool": {
                    item_uuid: conn.to_dict() 
                    for item_uuid, conn in self.room_listen_conn_pool.items()
                },
                "daemon_main_conn_state": {
                    api_key: state.to_dict() 
                    for api_key, state in self.daemon_main_conn_state.items()
                }
            }

    def _log_pool_state(self, message: str = "Pool State Updated"):
        logger.info(f"\n{'='*60}")
        logger.info(f"[BackendConnPool] {message}")
        logger.info(f"{'='*60}")
        logger.info(f"  Room监听连接池: {len(self.room_listen_conn_pool)} 个")
        for item_uuid, conn in self.room_listen_conn_pool.items():
            logger.info(f"    - {item_uuid[:20]}... | status={conn.status.value}")
        logger.info(f"  Daemon主连接状态: {len(self.daemon_main_conn_state)} 个")
        for api_key, state in self.daemon_main_conn_state.items():
            logger.info(f"    - {api_key[:16]}... | status={state.conn_status.value}")
        logger.info(f"{'='*60}\n")


backend_conn_pool = BackendConnPool()
