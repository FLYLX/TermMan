import os
import uuid
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from .connection_pool import ConnectionManager, DaemonConfig
from .socket_pool import SocketManager
from .connection_handler import ConnectionHandler
from .protocol import ProtocolEvents
from .log_manager import LogManager


class TerminalService:
    """
    终端核心业务逻辑
    """
    def __init__(self, connection_manager: ConnectionManager, socket_manager: SocketManager, connection_handler: ConnectionHandler):
        self.connection_manager = connection_manager
        self.socket_manager = socket_manager
        self.connection_handler = connection_handler
        self.log_manager = LogManager()
        self.terminal_users = {}  # 跟踪每个终端的连接用户 {item_uuid: [user_uuid1, user_uuid2, ...]}

    def start_terminal(self, item_uuid: str, user_uuid: str, daemon_config: DaemonConfig) -> Dict[str, Any]:
        """
        启动终端
        """
        # 确保与daemon的连接
        connection = self.connection_manager.get_or_create_connection(daemon_config)
        if not connection.is_connected():
            return {"success": False, "error": "Failed to connect to daemon"}

        # 生成终端token
        terminal_token = str(uuid.uuid4())

        # 使用HTTP方式启动终端
        result = connection.terminal_start_http(user_uuid, terminal_token)
        if not result.get("success"):
            return result

        # 使用daemon返回的item_uuid
        actual_item_uuid = result.get("item_uuid")
        self.socket_manager.add_token(actual_item_uuid, terminal_token)

        return {
            "success": True,
            "item_uuid": actual_item_uuid,
            "token": terminal_token,
            "daemon_url": daemon_config.base_url
        }

    def stop_terminal(self, daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """
        停止终端
        """
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon not connected"}
            
        # 使用HTTP方式停止终端
        return connection.terminal_stop_http(item_uuid)

    def get_terminal_status(self, daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """
        查询终端状态
        """
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon not connected"}
            
        # 使用HTTP方式获取终端状态
        return connection.terminal_status_http(item_uuid)

    def connect_terminal(self, item_uuid: str, token: str, daemon_url: str, user_uuid: Optional[str] = None, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        连接到终端
        """
        # 验证token
        if not self.socket_manager.validate_token(item_uuid, token):
            return None

        # 获取或创建socket连接
        socket = self.socket_manager.get_or_create_socket(item_uuid, token, daemon_url, user_uuid, api_key)
        if not socket.is_connected():
            return None
        
        # 将用户添加到终端的用户列表中
        if user_uuid:
            if item_uuid not in self.terminal_users:
                self.terminal_users[item_uuid] = []
            if user_uuid not in self.terminal_users[item_uuid]:
                self.terminal_users[item_uuid].append(user_uuid)
            
            # 注册日志回调，确保终端输出被记录到日志文件
            def log_callback(data):
                """仅用于记录日志的回调函数"""
                output = data.get("stdout", "")
                if output:
                    self.log_manager.write_to_log(user_uuid, item_uuid, output)
                stderr = data.get("stderr", "")
                if stderr:
                    self.log_manager.write_to_log(user_uuid, item_uuid, stderr)
            
            # 注册回调，确保日志被记录
            self.socket_manager.register_stream_callback(item_uuid, user_uuid, log_callback)

        return {
            "success": True,
            "item_uuid": item_uuid
        }

    def write_to_terminal(self, item_uuid: str, command: str) -> bool:
        """
        向终端写入命令
        """
        # 获取该终端的所有socket连接
        sockets = self.socket_manager.get_sockets_by_item(item_uuid)
        if not sockets:
            return False

        # 向第一个活跃的socket连接发送命令
        for socket in sockets:
            if socket.is_connected():
                return socket.write(command)
        return False
    
    def register_stream_callback(self, item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        """
        注册终端输出回调
        
        Args:
            item_uuid: 终端UUID
            user_uuid: 用户UUID，用于保存日志文件和关联socket
            callback: 用户提供的回调函数
            
        Returns:
            是否成功注册
        """
        # 创建一个包装函数，先保存日志，再调用用户回调
        def wrapped_callback(data):
            # 只保存当前用户的日志
            output = data.get("stdout", "")
            if output:
                self.log_manager.write_to_log(user_uuid, item_uuid, output)
            stderr = data.get("stderr", "")
            if stderr:
                self.log_manager.write_to_log(user_uuid, item_uuid, stderr)
            
            # 调用用户提供的回调
            callback(data)
        
        return self.socket_manager.register_stream_callback(item_uuid, user_uuid, wrapped_callback)

    def get_terminal_log(self, user_uuid: str, item_uuid: str) -> Optional[str]:
        """
        获取终端日志
        """
        return self.log_manager.get_log_content(user_uuid, item_uuid)

    def delete_terminal_log(self, user_uuid: str, item_uuid: str) -> bool:
        """
        删除终端日志
        """
        return self.log_manager.delete_log(user_uuid, item_uuid)
    
    def set_log_max_size(self, max_size: int) -> None:
        """
        设置日志文件最大大小
        
        Args:
            max_size: 最大大小，单位字节
        """
        self.log_manager.set_max_log_size(max_size)

    def list_user_terminals(self, user_uuid: str) -> Dict[str, Any]:
        """
        列出用户的所有终端
        """
        # 实际项目中应该从数据库获取
        # 这里简化实现
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
