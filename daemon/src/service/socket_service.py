import socketio
from typing import Dict, Any, List
import threading
from core import memory_store, config
from utils.logger import logger


class SocketService:
    """
    Socket.IO连接池管理
    """
    def __init__(self, sio: socketio.Server):
        self.sio = sio
        self.connections: Dict[str, List[str]] = {}  # item_uuid: [sid, ...]
        self.sid_to_item: Dict[str, str] = {}  # sid: item_uuid
        self.lock = threading.Lock()
        self.setup_event_handlers()

    def setup_event_handlers(self):
        """
        设置Socket.IO事件处理器
        """
        @self.sio.event
        async def connect(sid, environ, auth=None):
            """
            处理连接事件
            """
            # 认证逻辑
            if auth and "api_key" in auth:
                if auth["api_key"] == config.get("API_KEY"):
                    logger.info(f"Socket connected: {sid}")
                    return True
            logger.warning(f"Socket connection rejected: {sid}, invalid auth")
            return False

        @self.sio.event
        async def disconnect(sid):
            """
            处理断开连接事件
            """
            with self.lock:
                if sid in self.sid_to_item:
                    item_uuid = self.sid_to_item.pop(sid)
                    if item_uuid in self.connections:
                        self.connections[item_uuid].remove(sid)
                        if not self.connections[item_uuid]:
                            del self.connections[item_uuid]
                    logger.info(f"Socket disconnected: {sid}, item: {item_uuid}")
                else:
                    logger.info(f"Socket disconnected: {sid}")

        @self.sio.event
        async def terminal_connect(sid, data):
            """
            处理终端连接事件
            """
            item_uuid = data.get("item_uuid")
            token = data.get("token")

            if not item_uuid or not token:
                await self.sio.emit("auth_error", {"message": "Missing item_uuid or token"}, to=sid)
                return

            # 验证token
            stored_token = memory_store.get(f"terminal_token:{item_uuid}")
            if not stored_token or stored_token != token:
                await self.sio.emit("auth_error", {"message": "Invalid token"}, to=sid)
                return

            # 建立连接映射
            with self.lock:
                if item_uuid not in self.connections:
                    self.connections[item_uuid] = []
                self.connections[item_uuid].append(sid)
                self.sid_to_item[sid] = item_uuid

            await self.sio.emit("terminal_connected", {"item_uuid": item_uuid}, to=sid)
            logger.info(f"Terminal connected: {item_uuid}, sid: {sid}")

        @self.sio.event
        async def terminal_write(sid, data):
            """
            处理终端写入事件
            """
            with self.lock:
                if sid in self.sid_to_item:
                    item_uuid = self.sid_to_item[sid]
                    # 转发写入事件到终端管理器
                    from .terminal_manager import terminal_manager
                    terminal = terminal_manager.get_terminal(item_uuid)
                    if terminal:
                        terminal.write(data.get("command", "") + "\n")

    async def broadcast_to_terminal(self, item_uuid: str, event: str, data: Any):
        """
        向终端的所有连接广播事件
        """
        with self.lock:
            if item_uuid in self.connections:
                for sid in self.connections[item_uuid]:
                    try:
                        await self.sio.emit(event, data, to=sid)
                    except Exception as e:
                        logger.error(f"Failed to broadcast to {sid}: {e}")

    async def send_to_terminal(self, item_uuid: str, event: str, data: Any):
        """
        向终端发送事件（仅第一个连接）
        """
        with self.lock:
            if item_uuid in self.connections and self.connections[item_uuid]:
                sid = self.connections[item_uuid][0]
                try:
                    await self.sio.emit(event, data, to=sid)
                    return True
                except Exception as e:
                    logger.error(f"Failed to send to {sid}: {e}")
        return False

    async def close_terminal_connections(self, item_uuid: str):
        """
        关闭终端的所有连接
        """
        with self.lock:
            if item_uuid in self.connections:
                for sid in self.connections[item_uuid]:
                    try:
                        await self.sio.disconnect(sid)
                    except Exception as e:
                        logger.error(f"Failed to disconnect {sid}: {e}")
                del self.connections[item_uuid]

    def get_terminal_connections(self, item_uuid: str) -> List[str]:
        """
        获取终端的所有连接
        """
        with self.lock:
            return self.connections.get(item_uuid, [])

    def get_all_connections(self) -> Dict[str, List[str]]:
        """
        获取所有连接
        """
        with self.lock:
            return self.connections.copy()

    def get_connection_count(self) -> int:
        """
        获取总连接数
        """
        with self.lock:
            return sum(len(sids) for sids in self.connections.values())

    def get_terminal_count(self) -> int:
        """
        获取终端数
        """
        with self.lock:
            return len(self.connections)
