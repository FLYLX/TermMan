import logging
from typing import Any

from sqlmodel import Session

from app.core.db import engine
from app.models import Item

from .connection_pool import ConnectionManager, DaemonConfig, backend_conn_pool
from .log_manager import LogManager
from .socket_pool import SocketPoolFacade

logger = logging.getLogger(__name__)

log_manager = LogManager()


class TerminalService:
    """
    终端核心业务逻辑 - 按 UPDATE.MD 和 pool.md 规范实现 Room 机制
    
    核心设计：
    1. Backend 作为永久订阅者加入 Room，监听输出写日志
    2. Browser 作为临时订阅者加入 Room，实时渲染终端
    3. Item 启动时创建 Backend 永久订阅者连接
    4. Item 停止时销毁 Room，移除所有订阅者
    
    订阅模式：
    - ItemSocket 接收事件 -> 发布到 SubscriptionCenter
    - LogSubscriber 通过 SDK 订阅 -> 实时写入日志文件
    
    连接池管理：
    - ConnectionManager: 管理 Backend → Daemon 的主连接（管控指令）
    - SocketManager: 管理 Backend → Daemon Room 的监听连接（日志）
    - backend_conn_pool: 全局连接池单例
    """
    def __init__(self, connection_manager: ConnectionManager, socket_pool: SocketPoolFacade):
        self.connection_manager = connection_manager
        self.socket_pool = socket_pool
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
        
        self.socket_pool.register_item_token(
            daemon_config.daemon_id,
            actual_item_uuid,
            terminal_token,
        )
        
        backend_room_connected = self._create_backend_room_subscriber(
            actual_item_uuid,
            terminal_token,
            daemon_config.base_url,
            daemon_config.api_key,
            user_uuid
        )
        if not backend_room_connected:
            return {
                "success": False,
                "error": (
                    "终端进程已创建，但 Backend 未能进入对应 Socket Room。"
                    "请重试启动或检查 Backend 到 Daemon 的 WebSocket 连接。"
                ),
                "terminal_started": True,
                "item_uuid": actual_item_uuid,
            }

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
    ) -> bool:
        logger.info(f"[TerminalService] Creating backend socket for item={item_uuid}, daemon_url={daemon_url}")
        socket = self.socket_pool.ensure_backend_socket(
            item_uuid=item_uuid,
            token=token,
            daemon_url=daemon_url,
            api_key=api_key,
        )
        
        if not socket.is_connected():
            logger.error(f"[TerminalService] Backend socket failed to connect for item={item_uuid}")
            return False
        
        logger.info(f"[TerminalService] Backend socket connected for item={item_uuid}")
        
        self.socket_pool.ensure_log_subscription(
            item_uuid=item_uuid,
            owner_uuid=owner_uuid,
            log_manager=log_manager,
            subscriber_type="backend_log",
        )
        
        room_listen_conn = backend_conn_pool.create_room_listen_conn(item_uuid, api_key)
        room_listen_conn.set_connected(socket, socket.sio.sid if hasattr(socket.sio, 'sid') else None)
        
        backend_conn_pool._log_pool_state(f"Backend Room监听连接已建立: item={item_uuid}")
        
        if item_uuid not in self.terminal_users:
            self.terminal_users[item_uuid] = []
        if owner_uuid not in self.terminal_users[item_uuid]:
            self.terminal_users[item_uuid].append(owner_uuid)

        return True

    def restore_terminal_session(
        self,
        *,
        item_uuid: str,
        owner_uuid: str,
        daemon_config: DaemonConfig,
        token: str,
    ) -> bool:
        self.socket_pool.register_item_token(daemon_config.daemon_id, item_uuid, token)

        room_listen_conn = backend_conn_pool.get_room_listen_conn(item_uuid)
        backend_socket = self.socket_pool.get_backend_socket(item_uuid)
        if (
            room_listen_conn
            and room_listen_conn.is_connected()
            and backend_socket
            and backend_socket.is_connected()
        ):
            logger.info(
                f"[TerminalService] Existing backend room subscriber is already healthy for item={item_uuid}"
            )
            return True

        return self._create_backend_room_subscriber(
            item_uuid=item_uuid,
            token=token,
            daemon_url=daemon_config.base_url,
            api_key=daemon_config.api_key,
            owner_uuid=owner_uuid,
        )

    def restore_running_terminal(
        self,
        *,
        item_uuid: str,
        owner_uuid: str,
        daemon_config: DaemonConfig,
    ) -> bool:
        connection = self.connection_manager.get_or_create_connection(daemon_config)
        if not connection.is_connected():
            logger.warning(
                "[TerminalService] Cannot restore terminal because daemon is offline: item=%s",
                item_uuid,
            )
            return False

        try:
            status_result = connection.terminal_status_http(item_uuid)
        except Exception as exc:
            logger.warning(
                "[TerminalService] Failed to read daemon terminal status during restore: "
                "item=%s error=%s",
                item_uuid,
                exc,
            )
            return False
        if not status_result.get("success"):
            return False

        status_data = status_result.get("data") or {}
        terminal_status = str(status_data.get("status") or "")
        token = str(status_data.get("token") or "").strip()
        if terminal_status not in {"running", "waiting_backend"} or not token:
            return False

        return self.restore_terminal_session(
            item_uuid=item_uuid,
            owner_uuid=owner_uuid,
            daemon_config=daemon_config,
            token=token,
        )

    def stop_terminal(self, daemon_id: str, item_uuid: str) -> dict[str, Any]:
        connection = self.connection_manager.get_connection(daemon_id)
        if not connection or not connection.is_connected():
            return {"success": False, "error": "Daemon未连接"}

        result = connection.terminal_stop_http(item_uuid)
        
        if result.get("success"):
            self.socket_pool.cleanup_item_runtime(item_uuid)
            
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
            if not self.socket_pool.validate_item_token(daemon_id, item_uuid, token):
                return None
        else:
            found_daemon_id, found_token = self.socket_pool.get_item_token(item_uuid)
            if not found_token or found_token != token:
                return None
            daemon_id = found_daemon_id

        socket = self.socket_pool.ensure_browser_socket(
            item_uuid=item_uuid,
            token=token,
            daemon_url=daemon_url,
            user_uuid=user_uuid or "browser",
            api_key=api_key,
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
        return self.socket_pool.write_to_item(item_uuid, command)

    def get_terminal_log(self, user_uuid: str, item_uuid: str) -> str | None:
        return log_manager.get_log_content(user_uuid, item_uuid)

    def delete_terminal_log(self, user_uuid: str, item_uuid: str) -> bool:
        return log_manager.delete_log(user_uuid, item_uuid)

    def set_log_max_size(self, max_size: int) -> None:
        log_manager.set_max_log_size(max_size)

    def list_user_terminals(self, user_uuid: str) -> dict[str, Any]:
        terminals = []
        for socket in self.socket_pool.get_running_sockets():
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
