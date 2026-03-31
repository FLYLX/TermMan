import logging
import threading
from typing import Any

from .item_socket import ItemSocket
from .socket_models import TerminalStatus
from .subscription_center import subscription_center
from .input_center import input_center

logger = logging.getLogger(__name__)


class SocketManager:
    """
    Item Socket池管理 - 按 UPDATE.MD 和 pool.md 规范实现 Room 机制
    
    核心设计：
    1. Backend 作为永久订阅者（permanent）加入 Room，监听输出写日志
    2. Browser 作为临时订阅者（temporary）加入 Room，实时渲染终端
    3. 每个 item 可有多个 socket 连接（不同用户/不同类型）
    
    维护表：
    1. Item-Token映射表: {daemon_id: {item_uuid: token}}
    2. Socket实例表: {(user_uuid, item_uuid, subscriber_type) -> ItemSocket}
    
    注意：此管理器管理的是 Backend 主动创建的 Socket 连接
    """
    def __init__(self):
        self.sockets: dict[tuple[str, str, str], ItemSocket] = {}
        self.item_tokens: dict[str, dict[str, str]] = {}
        self.lock = threading.RLock()

    def get_socket(self, item_uuid: str, user_uuid: str, subscriber_type: str = "browser") -> ItemSocket | None:
        return self.sockets.get((user_uuid, item_uuid, subscriber_type))

    def get_sockets_by_item(self, item_uuid: str) -> list[ItemSocket]:
        return [sock for (_, iid, _), sock in self.sockets.items() if iid == item_uuid]

    def get_backend_socket(self, item_uuid: str) -> ItemSocket | None:
        return self.sockets.get(("backend", item_uuid, "backend"))

    def create_socket(
        self, 
        item_uuid: str, 
        token: str, 
        daemon_url: str, 
        user_uuid: str, 
        api_key: str | None = None, 
        subscriber_type: str = "browser"
    ) -> ItemSocket:
        socket = ItemSocket(item_uuid, token, daemon_url, user_uuid, subscriber_type)
        self.sockets[(user_uuid, item_uuid, subscriber_type)] = socket

        if api_key:
            socket.connect(api_key)

        self._print_socket_tables(f"Created {subscriber_type} Socket for Item {item_uuid}")
        return socket

    def create_backend_socket(self, item_uuid: str, token: str, daemon_url: str, api_key: str) -> ItemSocket:
        existing_socket = self.get_backend_socket(item_uuid)
        if existing_socket:
            if existing_socket.is_connected():
                logger.info(f"[SocketManager] Backend socket already exists and connected for item={item_uuid}, reusing")
                if not hasattr(existing_socket, '_input_handler_id') or not existing_socket._input_handler_id:
                    self._register_input_handler(existing_socket)
                return existing_socket
            else:
                logger.info(f"[SocketManager] Backend socket exists but disconnected for item={item_uuid}, reconnecting")
                existing_socket.connect(api_key)
                if existing_socket.is_connected():
                    if not hasattr(existing_socket, '_input_handler_id') or not existing_socket._input_handler_id:
                        self._register_input_handler(existing_socket)
                return existing_socket
        
        socket = self.create_socket(
            item_uuid=item_uuid,
            token=token,
            daemon_url=daemon_url,
            user_uuid="backend",
            api_key=api_key,
            subscriber_type="backend"
        )
        
        if socket.is_connected():
            self._register_input_handler(socket)
        else:
            logger.warning(f"[SocketManager] Backend socket NOT connected for item={item_uuid}")
        
        return socket
    
    def _register_input_handler(self, socket: ItemSocket):
        from .input_center import InputCommand
        
        def handle_input(cmd: InputCommand) -> bool:
            logger.info(f"[SocketManager] handle_input called: item={socket.item_uuid}, connected={socket.is_connected()}")
            if socket.is_connected():
                return socket.write(cmd.command)
            logger.warning(f"[SocketManager] handle_input: socket not connected for item={socket.item_uuid}")
            return False
        
        handler_id = input_center.register(
            item_uuid=socket.item_uuid,
            callback=handle_input,
            handler_type="backend_socket"
        )
        socket._input_handler_id = handler_id
        logger.info(f"[SocketManager] Registered input handler {handler_id} for item={socket.item_uuid}")
    
    def _unregister_input_handler(self, socket: ItemSocket):
        if hasattr(socket, '_input_handler_id'):
            input_center.unregister(socket._input_handler_id)
            logger.info(f"[SocketManager] Unregistered input handler {socket._input_handler_id} for item={socket.item_uuid}")

    def get_or_create_socket(
        self, 
        item_uuid: str, 
        token: str, 
        daemon_url: str, 
        user_uuid: str, 
        api_key: str | None = None, 
        subscriber_type: str = "browser"
    ) -> ItemSocket:
        socket = self.get_socket(item_uuid, user_uuid, subscriber_type)
        if not socket or not socket.is_connected():
            socket = self.create_socket(item_uuid, token, daemon_url, user_uuid, api_key, subscriber_type)
        return socket

    def remove_socket(self, item_uuid: str, user_uuid: str, subscriber_type: str = "browser"):
        with self.lock:
            key = (user_uuid, item_uuid, subscriber_type)
            if key in self.sockets:
                socket = self.sockets.pop(key)
                self._unregister_input_handler(socket)
                socket.disconnect()

    def remove_all_sockets_by_item(self, item_uuid: str):
        with self.lock:
            keys_to_remove = [(u, iid, s) for (u, iid, s) in self.sockets if iid == item_uuid]
            for key in keys_to_remove:
                socket = self.sockets.pop(key)
                self._unregister_input_handler(socket)
                socket.disconnect()

    def clear_sockets_by_item(self, item_uuid: str):
        with self.lock:
            keys_to_remove = [(u, iid, s) for (u, iid, s) in self.sockets if iid == item_uuid]
            for key in keys_to_remove:
                socket = self.sockets.pop(key)
                self._unregister_input_handler(socket)

    def add_token(self, daemon_id: str, item_uuid: str, token: str) -> dict[str, str]:
        with self.lock:
            if daemon_id not in self.item_tokens:
                self.item_tokens[daemon_id] = {}
            self.item_tokens[daemon_id][item_uuid] = token
            self._print_socket_tables(f"Added Token for Item {item_uuid}")
            return {'token': token}

    def get_token(self, daemon_id: str, item_uuid: str) -> str | None:
        with self.lock:
            return self.item_tokens.get(daemon_id, {}).get(item_uuid)

    def get_token_by_item(self, item_uuid: str) -> tuple[str | None, str | None]:
        with self.lock:
            for daemon_id, items in self.item_tokens.items():
                if item_uuid in items:
                    return (daemon_id, items[item_uuid])
            return (None, None)

    def remove_token(self, daemon_id: str, item_uuid: str) -> bool:
        with self.lock:
            if daemon_id in self.item_tokens and item_uuid in self.item_tokens[daemon_id]:
                del self.item_tokens[daemon_id][item_uuid]
                if not self.item_tokens[daemon_id]:
                    del self.item_tokens[daemon_id]
                return True
            return False

    def remove_all_tokens_by_item(self, item_uuid: str):
        with self.lock:
            for daemon_id in list(self.item_tokens.keys()):
                if item_uuid in self.item_tokens[daemon_id]:
                    del self.item_tokens[daemon_id][item_uuid]
                    if not self.item_tokens[daemon_id]:
                        del self.item_tokens[daemon_id]

    def validate_token(self, daemon_id: str, item_uuid: str, token: str) -> bool:
        stored_token = self.get_token(daemon_id, item_uuid)
        return stored_token is not None and stored_token == token

    def get_all_sockets(self) -> list[ItemSocket]:
        return list(self.sockets.values())

    def get_running_sockets(self) -> list[ItemSocket]:
        return [sock for sock in self.sockets.values() if sock.is_connected()]

    def get_user_sockets(self, user_uuid: str) -> list[ItemSocket]:
        return [sock for (u, _, _), sock in self.sockets.items() if u == user_uuid]

    def cleanup_disconnected_sockets(self):
        with self.lock:
            disconnected_keys = [
                (u, iid, s) for (u, iid, s), sock in self.sockets.items()
                if sock.get_status() == TerminalStatus.STOPPED
            ]
            for key in disconnected_keys:
                self.sockets.pop(key)

    def _print_socket_tables(self, message: str = "Socket Tables Updated"):
        logger.info(f"\n{'='*80}")
        logger.info(f"[Backend SocketManager] {message}")
        logger.info(f"{'='*80}")

        logger.info("\n1. Item-Token映射表 [daemon_id -> {item_uuid: token}]")
        logger.info("-" * 80)
        
        token_count = 0
        for daemon_id, items in self.item_tokens.items():
            for item_uuid, token in items.items():
                logger.info(f"  {daemon_id[:30]}... | {item_uuid[:20]}... | {token[:16]}...")
                token_count += 1

        if token_count == 0:
            logger.info("  无数据")
        else:
            logger.info(f"  共 {token_count} 个Token")

        logger.info("\n2. Socket实例表 [(user_uuid, item_uuid, type) -> ItemSocket]")
        logger.info("-" * 80)
        
        socket_count = 0
        for (user_uuid, item_uuid, stype), sock in self.sockets.items():
            status = "connected" if sock.is_connected() else "disconnected"
            logger.info(f"  {user_uuid[:20]}... | {item_uuid[:20]}... | {stype:<10} | {status}")
            socket_count += 1

        if socket_count == 0:
            logger.info("  无数据")
        else:
            logger.info(f"  共 {socket_count} 个Socket")

        logger.info(f"\n{'='*80}\n")
