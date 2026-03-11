import os
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from .connection_pool import ConnectionManager, DaemonConfig
from .socket_pool import SocketManager
from .connection_handler import ConnectionHandler
from .protocol import ProtocolEvents


class TerminalService:
    """
    终端核心业务逻辑
    """
    def __init__(self,
                 connection_manager: ConnectionManager,
                 socket_manager: SocketManager,
                 connection_handler: ConnectionHandler):
        self.connection_manager = connection_manager
        self.socket_manager = socket_manager
        self.connection_handler = connection_handler

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
        self.socket_manager.add_token(item_uuid, terminal_token)

        # 构建启动命令
        start_data = {
            "item_uuid": item_uuid,
            "user_uuid": user_uuid,
            "token": terminal_token
        }

        # 发送启动命令到daemon
        result = connection.emit(ProtocolEvents.TERMINAL_START, start_data)
        if not result:
            return {"success": False, "error": "Failed to send start command"}

        return {
            "success": True,
            "item_uuid": item_uuid,
            "token": terminal_token,
            "daemon_url": daemon_config.base_url
        }

    def stop_terminal(self, daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """
        停止终端
        """
        result = self.connection_handler.handle_terminal_stop(daemon_id, {
            "item_uuid": item_uuid
        })
        return result

    def get_terminal_status(self, daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """
        查询终端状态
        """
        result = self.connection_handler.handle_terminal_status(daemon_id, {
            "item_uuid": item_uuid
        })
        return result

    def connect_terminal(self, item_uuid: str, token: str, daemon_url: str) -> Optional[Dict[str, Any]]:
        """
        连接到终端
        """
        # 验证token
        if not self.socket_manager.validate_token(item_uuid, token):
            return None

        # 获取或创建socket连接
        socket = self.socket_manager.get_or_create_socket(item_uuid, token, daemon_url)
        if not socket.is_connected():
            return None

        return {
            "success": True,
            "item_uuid": item_uuid
        }

    def write_to_terminal(self, item_uuid: str, command: str) -> bool:
        """
        向终端写入命令
        """
        socket = self.socket_manager.get_socket(item_uuid)
        if not socket or not socket.is_connected():
            return False

        return socket.write(command)

    def get_terminal_log(self, user_uuid: str, item_uuid: str) -> Optional[str]:
        """
        获取终端日志
        """
        # 实际项目中应该从文件系统或数据库获取日志
        # 这里简化实现
        log_path = f"/tmp/terminals/{user_uuid}/{item_uuid}.log"
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                return f.read()
        return None

    def delete_terminal_log(self, user_uuid: str, item_uuid: str) -> bool:
        """
        删除终端日志
        """
        log_path = f"/tmp/terminals/{user_uuid}/{item_uuid}.log"
        if os.path.exists(log_path):
            os.remove(log_path)
            return True
        return False

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
