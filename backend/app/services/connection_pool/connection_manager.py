from typing import Dict, Optional, List
from .daemon_connection import DaemonConnection
from .connection_models import DaemonConfig, ConnectionStatus


class ConnectionManager:
    """
    Daemon连接池管理
    """
    def __init__(self):
        self.connections: Dict[str, DaemonConnection] = {}

    def get_connection(self, daemon_id: str) -> Optional[DaemonConnection]:
        """
        获取指定Daemon的连接
        """
        return self.connections.get(daemon_id)

    def create_connection(self, config: DaemonConfig) -> DaemonConnection:
        """
        创建新的Daemon连接
        """
        connection = DaemonConnection(config)
        self.connections[config.daemon_id] = connection
        connection.connect()
        return connection

    def get_or_create_connection(self, config: DaemonConfig) -> DaemonConnection:
        """
        获取或创建Daemon连接
        """
        connection = self.get_connection(config.daemon_id)
        if not connection or not connection.is_connected():
            connection = self.create_connection(config)
        return connection

    def remove_connection(self, daemon_id: str):
        """
        移除并关闭Daemon连接
        """
        if daemon_id in self.connections:
            connection = self.connections.pop(daemon_id)
            connection.disconnect()

    def get_all_connections(self) -> List[DaemonConnection]:
        """
        获取所有连接
        """
        return list(self.connections.values())

    def get_connected_connections(self) -> List[DaemonConnection]:
        """
        获取所有已连接的连接
        """
        return [conn for conn in self.connections.values() if conn.is_connected()]

    def heartbeat_all(self):
        """
        向所有连接发送心跳检测
        """
        for connection in self.connections.values():
            if connection.is_connected():
                connection.emit("heartbeat", {})

    def cleanup_disconnected(self):
        """
        清理断开的连接
        """
        disconnected_ids = [
            daemon_id for daemon_id, conn in self.connections.items()
            if conn.get_status() == ConnectionStatus.DISCONNECTED
        ]
        for daemon_id in disconnected_ids:
            self.remove_connection(daemon_id)
