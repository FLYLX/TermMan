from collections.abc import Callable
from typing import Any
import logging

from sqlmodel import Session

from app.core.db import engine
from app.models import Item

from .connection_pool import ConnectionManager, DaemonConfig, backend_conn_pool
from .log_manager import LogManager
from .protocol import ProtocolEvents
from .socket_pool import SocketManager

logger = logging.getLogger(__name__)


class TerminalService:
    """
    终端核心业务逻辑 - 按 UPDATE.MD 和 pool.md 规范实现 Room 机制
    
    核心设计：
    1. Backend 作为永久订阅者加入 Room，监听输出写日志
    2. Browser 作为临时订阅者加入 Room，实时渲染终端
    3. Item 启动时创建 Backend 永久订阅者连接
    4. Item 停止时销毁 Room，移除所有订阅者
    
    连接池管理：
    - ConnectionManager: 管理 Backend → Daemon 的主连接（管控指令）
    - SocketManager: 管理 Backend → Daemon Room 的监听连接（日志）
    - backend_conn_pool: 全局连接池单例
    """
    def __init__(self, connection_manager: ConnectionManager, socket_manager: SocketManager):
        self.connection_manager = connection_manager
        self.socket_manager = socket_manager
        self.log_manager = LogManager()
        self.terminal_users: dict[str, list[str]] = {}

    def start_terminal(self, item_uuid: str, user_uuid: str, daemon_config: DaemonConfig) -> dict[str, Any]:
        connection = self.connection_manager.get_or_create_connection(daemon_config)
        if not connection.is_connected():
            return {"success": False, "error": "无法连接到daemon"}

        with Session(engine) as session:
            item = session.query(Item).filter(Item.id == item_uuid).first()
            if not item:
                return {"success": False, "error": "Item不存在"}

        result = connection.terminal_start_http(
            user_uuid,
            item_uuid=item_uuid,
            working_directory=item.working_directory,
            command=item.command
        )
        if not result.get("success"):
            return result

        actual_item_uuid = result.get("item_uuid")
        terminal_token = result.get("token")
        already_running = result.get("already_running", False)
        
        self.socket_manager.add_token(daemon_config.daemon_id, actual_item_uuid, terminal_token)
        
        self._create_backend_room_subscriber(
            actual_item_uuid,
            terminal_token,
            daemon_config.base_url,
            daemon_config.api_key,
            user_uuid
        )

        response = {
            "success": True,
            "item_uuid": actual_item_uuid,
            "token": terminal_token,
            "daemon_url": daemon_config.base_url,
            "daemon_id": daemon_config.daemon_id
        }
        
        if already_running:
            response["already_running"] = True
            response["message"] = "该item终端已在运行中"
        
        return response

    def _create_backend_room_subscriber(
        self, 
        item_uuid: str, 
        token: str, 
        daemon_url: str, 
        api_key: str, 
        owner_uuid: str
    ):
        logger.info(f"[TerminalService] Creating backend socket for item={item_uuid}, daemon_url={daemon_url}")
        socket = self.socket_manager.create_backend_socket(
            item_uuid=item_uuid,
            token=token,
            daemon_url=daemon_url,
            api_key=api_key
        )
        
        if not socket.is_connected():
            logger.error(f"[TerminalService] Backend socket failed to connect for item={item_uuid}")
            return
        
        logger.info(f"[TerminalService] Backend socket connected for item={item_uuid}")
        
        def log_callback(data):
            output = data.get("stdout", "")
            stderr = data.get("stderr", "")
            logger.info(f"[TerminalService] log_callback called for item={item_uuid}: stdout={len(output)} chars, stderr={len(stderr)} chars")
            if output:
                success = self.log_manager.write_to_log(owner_uuid, item_uuid, output)
                logger.info(f"[TerminalService] Wrote stdout to log: success={success}")
            if stderr:
                success = self.log_manager.write_to_log(owner_uuid, item_uuid, stderr)
                logger.info(f"[TerminalService] Wrote stderr to log: success={success}")
        
        socket.on(ProtocolEvents.STREAM, log_callback)
        logger.info(f"[TerminalService] Registered STREAM callback for item={item_uuid}")
        
        room_listen_conn = backend_conn_pool.create_room_listen_conn(item_uuid, api_key)
        room_listen_conn.set_connected(socket, socket.sio.sid if hasattr(socket.sio, 'sid') else None)
        
        backend_conn_pool._log_pool_state(f"Backend Room监听连接已建立: item={item_uuid}")
        
        if item_uuid not in self.terminal_users:
            self.terminal_users[item_uuid] = []
        if owner_uuid not in self.terminal_users[item_uuid]:
            self.terminal_users[item_uuid].append(owner_uuid)

    def stop_terminal(self, daemon_id: str, item_uuid: str) -> dict[str, Any]:
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        result = connection.terminal_stop_http(item_uuid)
        
        if result.get("success"):
            self.socket_manager.remove_all_tokens_by_item(item_uuid)
            self.socket_manager.clear_sockets_by_item(item_uuid)
            
            backend_conn_pool.remove_room_listen_conn(item_uuid)
            
            if item_uuid in self.terminal_users:
                del self.terminal_users[item_uuid]
        
        return result

    def get_terminal_status(self, daemon_id: str, item_uuid: str) -> dict[str, Any]:
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        return connection.terminal_status_http(item_uuid)

    def connect_terminal(
        self, 
        item_uuid: str, 
        token: str, 
        daemon_url: str, 
        user_uuid: str | None = None, 
        api_key: str | None = None, 
        daemon_id: str | None = None
    ) -> dict[str, Any] | None:
        if daemon_id:
            if not self.socket_manager.validate_token(daemon_id, item_uuid, token):
                return None
        else:
            found_daemon_id, found_token = self.socket_manager.get_token_by_item(item_uuid)
            if not found_token or found_token != token:
                return None
            daemon_id = found_daemon_id

        socket = self.socket_manager.get_or_create_socket(
            item_uuid, token, daemon_url, user_uuid, api_key, subscriber_type="browser"
        )
        if not socket.is_connected():
            return None

        if user_uuid:
            if item_uuid not in self.terminal_users:
                self.terminal_users[item_uuid] = []
            if user_uuid not in self.terminal_users[item_uuid]:
                self.terminal_users[item_uuid].append(user_uuid)

        return {"success": True, "item_uuid": item_uuid}

    def write_to_terminal(self, item_uuid: str, command: str) -> bool:
        sockets = self.socket_manager.get_sockets_by_item(item_uuid)
        if not sockets:
            return False

        for socket in sockets:
            if socket.is_connected():
                return socket.write(command)
        return False

    def register_stream_callback(self, item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        return self.socket_manager.register_stream_callback(item_uuid, user_uuid, callback, "browser")

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
                "connected": socket.is_connected(),
                "subscriber_type": socket.subscriber_type
            })
        return {"user_uuid": user_uuid, "terminals": terminals}

    def disconnect_connection(self, daemon_id: str, item_uuid: str, ip_address: str) -> dict[str, Any]:
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        return connection.disconnect_connection_http(item_uuid, ip_address=ip_address)

    def get_item_connections(self, daemon_id: str, item_uuid: str) -> dict[str, Any]:
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        return connection.get_connections_http(item_uuid)
