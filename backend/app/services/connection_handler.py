from collections.abc import Callable
from typing import Any

from .connection_pool import ConnectionManager
from .protocol import ProtocolEvents
from .socket_pool import SocketManager


class ConnectionHandler:
    """
    统一连接处理器
    """
    def __init__(self, connection_manager: ConnectionManager, socket_manager: SocketManager):
        self.connection_manager = connection_manager
        self.socket_manager = socket_manager
        self.command_handlers: dict[str, Callable] = {}
        self.setup_command_handlers()

    def setup_command_handlers(self):
        """
        设置命令处理器
        """
        self.command_handlers[ProtocolEvents.TERMINAL_START] = self.handle_terminal_start
        self.command_handlers[ProtocolEvents.TERMINAL_STOP] = self.handle_terminal_stop
        self.command_handlers[ProtocolEvents.TERMINAL_STATUS] = self.handle_terminal_status

    def handle_command(self, daemon_id: str, command: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        处理命令
        """
        if command in self.command_handlers:
            try:
                return self.command_handlers[command](daemon_id, data)
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Unknown command"}

    def handle_terminal_start(self, daemon_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        处理终端启动命令
        """
        item_uuid = data.get("item_uuid")
        user_uuid = data.get("user_uuid")
        if not item_uuid or not user_uuid:
            return {"success": False, "error": "Missing required parameters"}

        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon not connected"}

        # 转发启动终端命令到daemon
        result = connection.emit(ProtocolEvents.TERMINAL_START, data)
        return {"success": result}

    def handle_terminal_stop(self, daemon_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        处理终端停止命令
        """
        item_uuid = data.get("item_uuid")
        if not item_uuid:
            return {"success": False, "error": "Missing item_uuid"}

        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon not connected"}

        # 转发停止终端命令到daemon
        result = connection.emit(ProtocolEvents.TERMINAL_STOP, data)

        # 清理本地socket连接 - 移除该item的所有socket连接
        self.socket_manager.remove_all_sockets_by_item(item_uuid)

        return {"success": result}

    def handle_terminal_status(self, daemon_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        处理终端状态查询命令
        """
        item_uuid = data.get("item_uuid")
        if not item_uuid:
            return {"success": False, "error": "Missing item_uuid"}

        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon not connected"}

        # 转发状态查询命令到daemon
        result = connection.emit(ProtocolEvents.TERMINAL_STATUS, data)
        return {"success": result}

    def forward_to_socket(self, item_uuid: str, event: str, data: Any) -> bool:
        """
        转发事件到Item Socket
        """
        # 获取该item的所有socket连接
        sockets = self.socket_manager.get_sockets_by_item(item_uuid)
        if not sockets:
            return False

        # 向第一个活跃的socket连接发送事件
        for socket in sockets:
            if socket.is_connected():
                return socket.emit(event, data)
        return False

    def broadcast_to_daemons(self, event: str, data: Any) -> int:
        """
        广播事件到所有Daemon
        """
        success_count = 0
        for connection in self.connection_manager.get_connected_connections():
            if connection.emit(event, data):
                success_count += 1
        return success_count

    def broadcast_to_sockets(self, event: str, data: Any) -> int:
        """
        广播事件到所有Item Socket
        """
        success_count = 0
        for socket in self.socket_manager.get_running_sockets():
            if socket.emit(event, data):
                success_count += 1
        return success_count
