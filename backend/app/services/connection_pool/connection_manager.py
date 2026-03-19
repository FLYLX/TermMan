from typing import Dict, Optional, List, Any
import logging
from .daemon_connection import DaemonConnection
from .connection_models import DaemonConfig, ConnectionStatus

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Daemon主连接管理器 - 管理 Backend → Daemon 的管控连接
    
    按 pool.md 规范：
    - 此连接池管理 Backend 主动向 Daemon 发起的主连接
    - 用于发送管控指令（启动/停止/重启终端等）
    - 与 BackendConnPool 中的 daemon_main_conn_state 配合使用
    
    连接池表: {daemon_id -> DaemonConnection}
    """
    def __init__(self):
        self.connections: Dict[str, DaemonConnection] = {}

    def get_connection(self, daemon_id: str) -> Optional[DaemonConnection]:
        return self.connections.get(daemon_id)

    def create_connection(self, config: DaemonConfig) -> DaemonConnection:
        connection = DaemonConnection(config)
        self.connections[config.daemon_id] = connection
        connection.connect()
        self._print_connection_pool("Created Daemon Connection")
        return connection

    def get_or_create_connection(self, config: DaemonConfig) -> DaemonConnection:
        connection = self.get_connection(config.daemon_id)
        if not connection:
            connection = self.create_connection(config)
        elif not connection.is_connected():
            logger.info(f"Connection {config.daemon_id} is disconnected, attempting to reconnect...")
            try:
                connection.connect()
            except Exception as e:
                logger.error(f"Failed to reconnect to {config.daemon_id}: {e}")
        return connection

    def reconnect_connection(self, config: DaemonConfig) -> Dict[str, Any]:
        daemon_id = config.daemon_id
        connection = self.get_connection(daemon_id)
        
        if connection:
            if connection.is_connected():
                return {
                    "success": True,
                    "message": f"Daemon {daemon_id} is already connected"
                }
            else:
                try:
                    connection.connect()
                    if connection.is_connected():
                        self._print_connection_pool(f"Reconnected Daemon: {daemon_id}")
                        return {
                            "success": True,
                            "message": f"Successfully reconnected to daemon {daemon_id}"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"Failed to reconnect to daemon {daemon_id}"
                        }
                except Exception as e:
                    logger.error(f"Failed to reconnect to {daemon_id}: {e}")
                    return {
                        "success": False,
                        "message": f"Failed to reconnect to daemon {daemon_id}: {str(e)}"
                    }
        else:
            try:
                new_connection = self.create_connection(config)
                if new_connection.is_connected():
                    return {
                        "success": True,
                        "message": f"Successfully connected to daemon {daemon_id}"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Failed to connect to daemon {daemon_id}"
                    }
            except Exception as e:
                logger.error(f"Failed to create connection to {daemon_id}: {e}")
                return {
                    "success": False,
                    "message": f"Failed to connect to daemon {daemon_id}: {str(e)}"
                }

    def remove_connection(self, daemon_id: str):
        if daemon_id in self.connections:
            connection = self.connections.pop(daemon_id)
            connection.disconnect()
            self._print_connection_pool("Removed Daemon Connection")

    def get_all_connections(self) -> List[DaemonConnection]:
        return list(self.connections.values())

    def get_connected_connections(self) -> List[DaemonConnection]:
        return [conn for conn in self.connections.values() if conn.is_connected()]

    def heartbeat_all(self):
        for connection in self.connections.values():
            if connection.is_connected():
                connection.emit("heartbeat", {})

    def cleanup_disconnected(self):
        disconnected_ids = [
            daemon_id for daemon_id, conn in self.connections.items()
            if conn.get_status() == ConnectionStatus.DISCONNECTED
        ]
        for daemon_id in disconnected_ids:
            self.remove_connection(daemon_id)

    def get_connection_pool(self) -> Dict[str, Any]:
        pool = {}
        for daemon_id, conn in self.connections.items():
            pool[daemon_id] = {
                "ip": conn.config.ip,
                "port": conn.config.port,
                "status": conn.get_status().value
            }
        return pool

    def _print_connection_pool(self, message: str = "Connection Pool Updated"):
        logger.info(f"\n{'='*60}")
        logger.info(f"{message}")
        logger.info(f"{'='*60}")
        logger.info("\nDaemon主连接池表 [daemon ip:port:apikey]")
        logger.info("-" * 80)
        logger.info(f"{'Daemon ID':<50} | {'Status':<15}")
        logger.info("-" * 80)
        
        for daemon_id, conn in self.connections.items():
            status = conn.get_status().value
            logger.info(f"{daemon_id:<50} | {status:<15}")
        
        if not self.connections:
            logger.info("  无连接")
        
        logger.info(f"\n{'='*60}")
