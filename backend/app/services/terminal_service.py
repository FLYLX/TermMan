from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from app.core.db import engine
from app.models import Item

from .connection_handler import ConnectionHandler
from .connection_pool import ConnectionManager, DaemonConfig
from .log_manager import LogManager
from .socket_pool import SocketManager


class TerminalService:
    """
    终端核心业务逻辑 - 按 UPDATE.MD 重构
    """
    def __init__(self, connection_manager: ConnectionManager, socket_manager: SocketManager, connection_handler: ConnectionHandler):
        self.connection_manager = connection_manager
        self.socket_manager = socket_manager
        self.connection_handler = connection_handler
        self.log_manager = LogManager()
        self.terminal_users = {}

    def start_terminal(self, item_uuid: str, user_uuid: str, daemon_config: DaemonConfig) -> dict[str, Any]:
        """
        启动终端
        
        流程：
        1. 确保与daemon的连接
        2. 发送start请求到daemon
        3. 获取daemon返回的token和连接池
        4. 更新后端的连接池表
        5. 创建backend socket连接
        """
        connection = self.connection_manager.get_or_create_connection(daemon_config)
        if not connection.is_connected():
            return {"success": False, "error": "无法连接到daemon"}

        with Session(engine) as session:
            item = session.query(Item).filter(Item.id == item_uuid).first()
            if not item:
                return {"success": False, "error": "Item不存在"}

        result = connection.terminal_start_http(user_uuid,
                                               item_uuid=item_uuid,
                                               working_directory=item.working_directory,
                                               command=item.command)
        if not result.get("success"):
            return result

        actual_item_uuid = result.get("item_uuid")
        terminal_token = result.get("token")
        connections = result.get("connections", {})
        
        self.socket_manager.add_token(daemon_config.daemon_id, actual_item_uuid, terminal_token)
        
        if connections:
            self.socket_manager.update_connections_from_daemon(actual_item_uuid, connections)
        
        self.socket_manager.create_socket(
            actual_item_uuid, 
            terminal_token, 
            daemon_config.base_url, 
            "backend",
            daemon_config.api_key,
            "backend",
            None
        )

        return {
            "success": True,
            "item_uuid": actual_item_uuid,
            "token": terminal_token,
            "daemon_url": daemon_config.base_url,
            "daemon_id": daemon_config.daemon_id,
            "connections": connections
        }

    def stop_terminal(self, daemon_id: str, item_uuid: str) -> dict[str, Any]:
        """
        停止终端
        
        流程：
        1. 发送stop请求到daemon
        2. 获取daemon返回的空连接池
        3. 更新后端的连接池表（清空）
        4. 移除token
        """
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        result = connection.terminal_stop_http(item_uuid)
        
        if result.get("success"):
            self.socket_manager.update_connections_from_daemon(item_uuid, {})
            self.socket_manager.remove_all_tokens_by_item(item_uuid)
            self.socket_manager.remove_all_sockets_by_item(item_uuid)
        
        return result

    def get_terminal_status(self, daemon_id: str, item_uuid: str) -> dict[str, Any]:
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        return connection.terminal_status_http(item_uuid)

    def connect_terminal(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str | None = None, api_key: str | None = None, daemon_id: str | None = None) -> dict[str, Any] | None:
        """
        连接到终端
        """
        if daemon_id:
            if not self.socket_manager.validate_token(daemon_id, item_uuid, token):
                return None
        else:
            found_daemon_id, found_token = self.socket_manager.get_token_by_item(item_uuid)
            if not found_token or found_token != token:
                return None
            daemon_id = found_daemon_id

        socket = self.socket_manager.get_or_create_socket(item_uuid, token, daemon_url, user_uuid, api_key)
        if not socket.is_connected():
            return None

        if user_uuid:
            if item_uuid not in self.terminal_users:
                self.terminal_users[item_uuid] = []
            if user_uuid not in self.terminal_users[item_uuid]:
                self.terminal_users[item_uuid].append(user_uuid)

            def log_callback(data):
                output = data.get("stdout", "")
                if output:
                    self.log_manager.write_to_log(user_uuid, item_uuid, output)
                stderr = data.get("stderr", "")
                if stderr:
                    self.log_manager.write_to_log(user_uuid, item_uuid, stderr)

            self.socket_manager.register_stream_callback(item_uuid, user_uuid, log_callback)

        return {
            "success": True,
            "item_uuid": item_uuid
        }

    def write_to_terminal(self, item_uuid: str, command: str) -> bool:
        sockets = self.socket_manager.get_sockets_by_item(item_uuid)
        if not sockets:
            return False

        for socket in sockets:
            if socket.is_connected():
                return socket.write(command)
        return False

    def register_stream_callback(self, item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        def wrapped_callback(data):
            output = data.get("stdout", "")
            if output:
                self.log_manager.write_to_log(user_uuid, item_uuid, output)
            stderr = data.get("stderr", "")
            if stderr:
                self.log_manager.write_to_log(user_uuid, item_uuid, stderr)

            callback(data)

        return self.socket_manager.register_stream_callback(item_uuid, user_uuid, wrapped_callback)

    def get_terminal_log(self, user_uuid: str, item_uuid: str) -> str | None:
        return self.log_manager.get_log_content(user_uuid, item_uuid)

    def delete_terminal_log(self, user_uuid: str, item_uuid: str) -> bool:
        return self.log_manager.delete_log(user_uuid, item_uuid)

    def set_log_max_size(self, max_size: int) -> None:
        self.log_manager.set_max_log_size(max_size)

    def list_user_terminals(self, user_uuid: str) -> dict[str, Any]:
        terminals = []
        for socket in self.socket_manager.get_running_sockets():
            terminals.append({
                "item_uuid": socket.item_uuid,
                "status": socket.status.value,
                "connected": socket.is_connected()
            })
        return {
            "user_uuid": user_uuid,
            "terminals": terminals
        }

    def disconnect_connection(self, daemon_id: str, item_uuid: str, ip_address: str) -> dict[str, Any]:
        """
        断开特定连接
        
        流程：
        1. 发送disconnect请求到daemon
        2. 获取daemon返回的更新后的连接池
        3. 更新后端的连接池表
        """
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        result = connection.disconnect_connection_http(item_uuid, ip_address)
        
        if result.get("success"):
            connections = result.get("connections", {})
            self.socket_manager.update_connections_from_daemon(item_uuid, connections)
        
        return result

    def get_item_connections(self, daemon_id: str, item_uuid: str) -> dict[str, Any]:
        """
        获取item的连接池
        """
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        result = connection.get_connections_http(item_uuid)
        
        if result.get("success"):
            connections = result.get("connections", {})
            self.socket_manager.update_connections_from_daemon(item_uuid, connections)
        
        return result
