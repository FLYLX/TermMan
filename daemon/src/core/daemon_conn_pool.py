import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from utils.logger import logger


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class AuthStatus(str, Enum):
    UNAUTHENTICATED = "unauthenticated"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"


class BackendMainConnection:
    """
    Backend主连接 - Daemon ↔ Backend 管控连接
    
    按 pool.md 规范实现
    """
    def __init__(self, daemon_api_key: str):
        self.daemon_api_key = daemon_api_key
        self.conn: Optional[Any] = None
        self.conn_id: Optional[str] = None
        self.auth_token: Optional[str] = None
        self.status = ConnectionStatus.DISCONNECTED
        self.last_heartbeat: Optional[float] = None
        self.heartbeat_interval = 30
        self.reconnect_times = 0
        self.max_reconnect_times = 10
        self.lock = threading.Lock()

    def set_connected(self, conn: Any, conn_id: str, auth_token: str = None):
        with self.lock:
            self.conn = conn
            self.conn_id = conn_id
            self.auth_token = auth_token
            self.status = ConnectionStatus.CONNECTED
            self.last_heartbeat = datetime.now().timestamp()
            self.reconnect_times = 0

    def set_disconnected(self):
        with self.lock:
            self.status = ConnectionStatus.DISCONNECTED

    def update_heartbeat(self):
        with self.lock:
            self.last_heartbeat = datetime.now().timestamp()

    def is_connected(self) -> bool:
        with self.lock:
            return self.status == ConnectionStatus.CONNECTED and self.conn is not None

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "daemon_api_key": self.daemon_api_key,
                "conn_id": self.conn_id,
                "status": self.status.value,
                "last_heartbeat": self.last_heartbeat,
                "reconnect_times": self.reconnect_times
            }


class BrowserTerminalConnection:
    """
    浏览器终端连接 - Daemon ↔ 浏览器 终端交互
    
    按 pool.md 规范实现
    """
    def __init__(self, sid: str, item_uuid: str, temp_token: str = None):
        self.sid = sid
        self.item_uuid = item_uuid
        self.temp_token = temp_token
        self.conn: Optional[Any] = None
        self.conn_id: Optional[str] = None
        self.user_uuid: Optional[str] = None
        self.auth_status = AuthStatus.UNAUTHENTICATED
        self.ip: Optional[str] = None
        self.join_time: float = datetime.now().timestamp()
        self.last_active_time: float = datetime.now().timestamp()
        self.lock = threading.Lock()

    def set_authenticated(self, user_uuid: str, conn: Any = None):
        with self.lock:
            self.user_uuid = user_uuid
            self.auth_status = AuthStatus.AUTHENTICATED
            if conn:
                self.conn = conn
            self.last_active_time = datetime.now().timestamp()

    def set_expired(self):
        with self.lock:
            self.auth_status = AuthStatus.EXPIRED

    def update_active_time(self):
        with self.lock:
            self.last_active_time = datetime.now().timestamp()

    def is_authenticated(self) -> bool:
        with self.lock:
            return self.auth_status == AuthStatus.AUTHENTICATED

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "sid": self.sid,
                "item_uuid": self.item_uuid,
                "user_uuid": self.user_uuid,
                "auth_status": self.auth_status.value,
                "ip": self.ip,
                "join_time": self.join_time,
                "last_active_time": self.last_active_time
            }


class BackendRoomListenConnection:
    """
    Backend Room监听连接 - Daemon ↔ Backend 日志监听
    
    按 pool.md 规范实现
    """
    def __init__(self, item_uuid: str):
        self.item_uuid = item_uuid
        self.room_id = item_uuid
        self.conn: Optional[Any] = None
        self.conn_id: Optional[str] = None
        self.auth_token: Optional[str] = None
        self.status = ConnectionStatus.DISCONNECTED
        self.is_permanent = True
        self.last_heartbeat: Optional[float] = None
        self.reconnect_notify = False
        self.lock = threading.Lock()

    def set_connected(self, conn: Any, conn_id: str, auth_token: str = None):
        with self.lock:
            self.conn = conn
            self.conn_id = conn_id
            self.auth_token = auth_token
            self.status = ConnectionStatus.CONNECTED
            self.last_heartbeat = datetime.now().timestamp()
            self.reconnect_notify = False
        logger.info(f"[BackendRoomListenConnection] item={self.item_uuid} connected, conn_id={conn_id}")

    def set_disconnected(self):
        with self.lock:
            self.status = ConnectionStatus.DISCONNECTED
            self.reconnect_notify = True

    def update_heartbeat(self):
        with self.lock:
            self.last_heartbeat = datetime.now().timestamp()

    def is_connected(self) -> bool:
        with self.lock:
            return self.status == ConnectionStatus.CONNECTED and self.conn is not None

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "item_uuid": self.item_uuid,
                "room_id": self.room_id,
                "conn_id": self.conn_id,
                "status": self.status.value,
                "is_permanent": self.is_permanent,
                "last_heartbeat": self.last_heartbeat,
                "reconnect_notify": self.reconnect_notify
            }


class DaemonConnPool:
    """
    Daemon全局连接池（单例 + 线程锁）
    
    按 pool.md 规范实现三个连接池表：
    1. backend_main_conn_pool: Backend主连接池（Daemon ↔ Backend 管控连接）
    2. browser_terminal_conn_pool: 浏览器终端连接池（Daemon ↔ 浏览器 终端交互）
    3. backend_room_listen_conn_pool: Backend Room监听连接池（Daemon ↔ Backend 日志监听）
    
    核心原则：
    - 所有连接池都按 item_uuid 隔离
    - 保证通信不交叉
    - 线程安全
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.backend_main_conn_pool: Dict[str, BackendMainConnection] = {}
                cls._instance.browser_terminal_conn_pool: Dict[str, List[BrowserTerminalConnection]] = {}
                cls._instance.backend_room_listen_conn_pool: Dict[str, BackendRoomListenConnection] = {}
                cls._instance._pool_lock = threading.Lock()
            return cls._instance

    def create_backend_main_conn(self, daemon_api_key: str) -> BackendMainConnection:
        with self._pool_lock:
            if daemon_api_key in self.backend_main_conn_pool:
                return self.backend_main_conn_pool[daemon_api_key]
            
            conn = BackendMainConnection(daemon_api_key)
            self.backend_main_conn_pool[daemon_api_key] = conn
            self._log_pool_state(f"Created BackendMainConnection for daemon={daemon_api_key[:16]}...")
            return conn

    def get_backend_main_conn(self, daemon_api_key: str) -> Optional[BackendMainConnection]:
        with self._pool_lock:
            return self.backend_main_conn_pool.get(daemon_api_key)

    def remove_backend_main_conn(self, daemon_api_key: str) -> Optional[BackendMainConnection]:
        with self._pool_lock:
            conn = self.backend_main_conn_pool.pop(daemon_api_key, None)
            if conn:
                self._log_pool_state(f"Removed BackendMainConnection for daemon={daemon_api_key[:16]}...")
            return conn

    def get_all_backend_main_conns(self) -> List[BackendMainConnection]:
        with self._pool_lock:
            return list(self.backend_main_conn_pool.values())

    def create_browser_terminal_conn(self, item_uuid: str, sid: str, temp_token: str = None) -> BrowserTerminalConnection:
        with self._pool_lock:
            if item_uuid not in self.browser_terminal_conn_pool:
                self.browser_terminal_conn_pool[item_uuid] = []
            
            for conn in self.browser_terminal_conn_pool[item_uuid]:
                if conn.sid == sid:
                    return conn
            
            conn = BrowserTerminalConnection(sid, item_uuid, temp_token)
            self.browser_terminal_conn_pool[item_uuid].append(conn)
            self._log_pool_state(f"Created BrowserTerminalConnection for item={item_uuid}, sid={sid[:16]}...")
            return conn

    def get_browser_terminal_conns(self, item_uuid: str) -> List[BrowserTerminalConnection]:
        with self._pool_lock:
            return self.browser_terminal_conn_pool.get(item_uuid, [])

    def get_browser_terminal_conn(self, item_uuid: str, sid: str) -> Optional[BrowserTerminalConnection]:
        with self._pool_lock:
            conns = self.browser_terminal_conn_pool.get(item_uuid, [])
            for conn in conns:
                if conn.sid == sid:
                    return conn
            return None

    def remove_browser_terminal_conn(self, item_uuid: str, sid: str) -> Optional[BrowserTerminalConnection]:
        with self._pool_lock:
            if item_uuid not in self.browser_terminal_conn_pool:
                return None
            
            for i, conn in enumerate(self.browser_terminal_conn_pool[item_uuid]):
                if conn.sid == sid:
                    removed = self.browser_terminal_conn_pool[item_uuid].pop(i)
                    if not self.browser_terminal_conn_pool[item_uuid]:
                        del self.browser_terminal_conn_pool[item_uuid]
                    self._log_pool_state(f"Removed BrowserTerminalConnection for item={item_uuid}, sid={sid[:16]}...")
                    return removed
            return None

    def remove_all_browser_terminal_conns(self, item_uuid: str) -> List[BrowserTerminalConnection]:
        with self._pool_lock:
            conns = self.browser_terminal_conn_pool.pop(item_uuid, [])
            if conns:
                self._log_pool_state(f"Removed all BrowserTerminalConnections for item={item_uuid}")
            return conns

    def get_all_browser_terminal_conns(self) -> Dict[str, List[BrowserTerminalConnection]]:
        with self._pool_lock:
            return {k: v.copy() for k, v in self.browser_terminal_conn_pool.items()}

    def create_backend_room_listen_conn(self, item_uuid: str) -> BackendRoomListenConnection:
        with self._pool_lock:
            if item_uuid in self.backend_room_listen_conn_pool:
                return self.backend_room_listen_conn_pool[item_uuid]
            
            conn = BackendRoomListenConnection(item_uuid)
            self.backend_room_listen_conn_pool[item_uuid] = conn
            logger.info(f"[DaemonConnPool] Created BackendRoomListenConnection for item={item_uuid} (status=disconnected, waiting for set_connected)")
            return conn

    def get_backend_room_listen_conn(self, item_uuid: str) -> Optional[BackendRoomListenConnection]:
        with self._pool_lock:
            return self.backend_room_listen_conn_pool.get(item_uuid)

    def remove_backend_room_listen_conn(self, item_uuid: str) -> Optional[BackendRoomListenConnection]:
        with self._pool_lock:
            conn = self.backend_room_listen_conn_pool.pop(item_uuid, None)
            if conn:
                self._log_pool_state(f"Removed BackendRoomListenConnection for item={item_uuid}")
            return conn

    def get_all_backend_room_listen_conns(self) -> List[BackendRoomListenConnection]:
        with self._pool_lock:
            return list(self.backend_room_listen_conn_pool.values())

    def get_pool_state(self) -> Dict[str, Any]:
        with self._pool_lock:
            return {
                "backend_main_conn_pool": {
                    api_key: conn.to_dict() 
                    for api_key, conn in self.backend_main_conn_pool.items()
                },
                "browser_terminal_conn_pool": {
                    item_uuid: [conn.to_dict() for conn in conns]
                    for item_uuid, conns in self.browser_terminal_conn_pool.items()
                },
                "backend_room_listen_conn_pool": {
                    item_uuid: conn.to_dict() 
                    for item_uuid, conn in self.backend_room_listen_conn_pool.items()
                }
            }

    def _log_pool_state(self, message: str = "Pool State Updated"):
        logger.info(f"\n{'='*60}")
        logger.info(f"[DaemonConnPool] {message}")
        logger.info(f"{'='*60}")
        logger.info(f"  Backend主连接池: {len(self.backend_main_conn_pool)} 个")
        for api_key, conn in self.backend_main_conn_pool.items():
            logger.info(f"    - {api_key[:16]}... | status={conn.status.value}")
        
        logger.info(f"  浏览器终端连接池: {len(self.browser_terminal_conn_pool)} 个Item")
        for item_uuid, conns in self.browser_terminal_conn_pool.items():
            logger.info(f"    - {item_uuid[:20]}... | {len(conns)} 个连接")
        
        logger.info(f"  Backend Room监听连接池: {len(self.backend_room_listen_conn_pool)} 个")
        for item_uuid, conn in self.backend_room_listen_conn_pool.items():
            logger.info(f"    - {item_uuid[:20]}... | status={conn.status.value}")
        logger.info(f"{'='*60}\n")


daemon_conn_pool = DaemonConnPool()
