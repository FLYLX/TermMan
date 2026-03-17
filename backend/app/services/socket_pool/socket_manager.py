import logging
from collections.abc import Callable
from typing import Any

from ..protocol import ProtocolEvents
from .item_socket import ItemSocket
from .socket_models import TerminalStatus

logger = logging.getLogger(__name__)


class SocketManager:
    """
    Item Socket池管理 - 按 UPDATE.MD 简化版连接表
    
    维护两张表：
    1. Item-Token映射表: {daemon_id: {item_uuid: token}}
    2. Item-连接映射表: [item_uuid -> {sid -> {user_uuid, ip}}]
    
    广播是对所有 {sid: user_uuid, ip_address}
    单播根据 ip_address 来查找对应的 socket 连接
    """
    def __init__(self):
        import threading
        self.sockets: dict[tuple, ItemSocket] = {}

        self.item_tokens: dict[str, dict[str, str]] = {}  # daemon_id -> {item_uuid: token}

        self.connections: dict[str, dict[str, dict[str, str]]] = {}  # item_uuid -> {sid -> {user_uuid, ip}}

        self.lock = threading.RLock()

    def get_socket(self, item_uuid: str, user_uuid: str) -> ItemSocket | None:
        return self.sockets.get((user_uuid, item_uuid))

    def get_sockets_by_item(self, item_uuid: str) -> list[ItemSocket]:
        return [sock for (uuid, iid), sock in self.sockets.items() if iid == item_uuid]

    def create_socket(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str, api_key: str | None = None, ip_address: str = "unknown", sid: str | None = None) -> ItemSocket:
        import uuid as uuid_lib
        socket = ItemSocket(item_uuid, token, daemon_url, user_uuid)
        self.sockets[(user_uuid, item_uuid)] = socket

        if item_uuid not in self.connections:
            self.connections[item_uuid] = {}

        connection_sid = sid or str(uuid_lib.uuid4())
        self.connections[item_uuid][connection_sid] = {
            'user_uuid': user_uuid,
            'ip': ip_address
        }

        if api_key:
            socket.connect(api_key)

        self._print_connection_tables(f"Created Socket Connection for Item {item_uuid} by User {user_uuid}")
        return socket

    def get_or_create_socket(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str, api_key: str | None = None, ip_address: str = "unknown", sid: str | None = None) -> ItemSocket:
        socket = self.get_socket(item_uuid, user_uuid)
        if not socket or not socket.is_connected():
            socket = self.create_socket(item_uuid, token, daemon_url, user_uuid, api_key, ip_address, sid)
        return socket

    def remove_socket(self, item_uuid: str, user_uuid: str):
        with self.lock:
            key = (user_uuid, item_uuid)
            if key in self.sockets:
                socket = self.sockets.pop(key)
                socket.disconnect()

            if item_uuid in self.connections:
                sids_to_remove = [
                    sid for sid, conn_info in self.connections[item_uuid].items()
                    if conn_info['user_uuid'] == user_uuid
                ]
                for sid in sids_to_remove:
                    self.connections[item_uuid].pop(sid)

                if not self.connections[item_uuid]:
                    self.connections.pop(item_uuid)

    def remove_all_sockets_by_item(self, item_uuid: str):
        with self.lock:
            keys_to_remove = [(user_uuid, iid) for (user_uuid, iid), sock in self.sockets.items() if iid == item_uuid]

            for key in keys_to_remove:
                socket = self.sockets.pop(key)
                socket.disconnect()

            if item_uuid in self.connections:
                self.connections.pop(item_uuid)

    def add_token(self, daemon_id: str, item_uuid: str, token: str) -> dict[str, str]:
        """
        添加Token信息
        
        Args:
            daemon_id: Daemon标识符
            item_uuid: 项目UUID
            token: Token字符串
            
        Returns:
            Token信息字典
        """
        with self.lock:
            logger.info(f"Adding token for daemon {daemon_id}, item {item_uuid}")
            
            if daemon_id not in self.item_tokens:
                self.item_tokens[daemon_id] = {}
            
            self.item_tokens[daemon_id][item_uuid] = token
            
            self._print_connection_tables(f"Added Token for Item {item_uuid}")
            return {'token': token}

    def get_token(self, daemon_id: str, item_uuid: str) -> str | None:
        """
        获取Token信息
        
        Args:
            daemon_id: Daemon标识符
            item_uuid: 项目UUID
            
        Returns:
            Token字符串，如果不存在返回 None
        """
        with self.lock:
            if daemon_id in self.item_tokens:
                return self.item_tokens[daemon_id].get(item_uuid)
            return None

    def get_token_by_item(self, item_uuid: str) -> tuple[str | None, str | None]:
        """
        根据item_uuid获取daemon_id和token
        
        Args:
            item_uuid: 项目UUID
            
        Returns:
            (daemon_id, token) 元组，如果不存在返回 (None, None)
        """
        with self.lock:
            for daemon_id, items in self.item_tokens.items():
                if item_uuid in items:
                    return (daemon_id, items[item_uuid])
            return (None, None)

    def remove_token(self, daemon_id: str, item_uuid: str) -> bool:
        with self.lock:
            if daemon_id in self.item_tokens and item_uuid in self.item_tokens[daemon_id]:
                del self.item_tokens[daemon_id][item_uuid]
                logger.info(f"Removed token for item {item_uuid}")
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
        with self.lock:
            stored_token = self.get_token(daemon_id, item_uuid)
            return stored_token is not None and stored_token == token

    def get_all_sockets(self) -> list[ItemSocket]:
        return list(self.sockets.values())

    def get_running_sockets(self) -> list[ItemSocket]:
        return [sock for sock in self.sockets.values() if sock.is_connected()]

    def get_connection_tables(self) -> dict[str, Any]:
        """
        获取所有连接表
        
        Returns:
            包含 item_tokens 和 item_connections 的字典
        """
        return {
            'item_tokens': {k: v.copy() for k, v in self.item_tokens.items()},
            'item_connections': {k: v.copy() for k, v in self.connections.items()}
        }

    def disconnect_user_from_item(self, item_uuid: str, user_uuid: str) -> bool:
        try:
            self.remove_socket(item_uuid, user_uuid)
            return True
        except Exception:
            return False

    def get_user_sockets(self, user_uuid: str) -> list[ItemSocket]:
        return [sock for (uuid, iid), sock in self.sockets.items() if uuid == user_uuid]

    def register_stream_callback(self, item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        socket = self.get_socket(item_uuid, user_uuid)
        if socket and socket.is_connected():
            socket.on(ProtocolEvents.STREAM, callback)
            return True
        return False

    def cleanup_disconnected_sockets(self):
        disconnected_items = [
            (user_uuid, iid) for (user_uuid, iid), sock in self.sockets.items()
            if sock.get_status() == TerminalStatus.STOPPED
        ]
        for user_uuid, item_uuid in disconnected_items:
            self.remove_socket(item_uuid, user_uuid)

    def _print_connection_tables(self, message: str = "Connection Tables Updated"):
        logger.info(f"\n{'='*80}")
        logger.info(f"[Backend SocketManager] {message}")
        logger.info(f"{'='*80}")

        tables = self.get_connection_tables()

        logger.info("\n1. Item-Token映射表 [daemon_id -> {item_uuid: token}]")
        logger.info("-" * 100)
        logger.info(f"{'Daemon ID':<40} | {'Item UUID':<36} | {'Token':<36}")
        logger.info("-" * 100)

        token_count = 0
        for daemon_id, items in tables['item_tokens'].items():
            for item_uuid, token in items.items():
                logger.info(f"{daemon_id:<40} | {item_uuid:<36} | {token[:16]}...")
                token_count += 1

        if token_count == 0:
            logger.info("  无数据")
        else:
            logger.info(f"  共 {token_count} 个Token")

        logger.info("\n2. Item-连接映射表 [item_uuid -> {sid -> {user_uuid, ip}}]")
        logger.info("-" * 100)
        logger.info(f"{'Item UUID':<36} | {'SID':<36} | {'User UUID':<36} | {'IP':<15}")
        logger.info("-" * 100)

        conn_count = 0
        for item_uuid, sids in tables['item_connections'].items():
            for sid, conn_info in sids.items():
                user_uuid = conn_info.get('user_uuid', 'unknown')
                ip = conn_info.get('ip', 'unknown')
                logger.info(f"{item_uuid:<36} | {sid[:16]}...{' '*17} | {user_uuid:<36} | {ip:<15}")
                conn_count += 1

        if conn_count == 0:
            logger.info("  无数据")
        else:
            logger.info(f"  共 {conn_count} 个连接")

        logger.info(f"\n{'='*80}\n")

    def import_socket_connections(self, item_uuid: str, connections: dict[str, Any], daemon_url: str, api_key: str, daemon_id: str = None) -> bool:
        """
        从daemon导入socket连接表
        
        Args:
            item_uuid: 项目UUID
            connections: daemon返回的连接表，格式为 {sid: {user_uuid, ip}}
            daemon_url: daemon的URL
            api_key: API密钥
            daemon_id: Daemon标识符
            
        Returns:
            是否成功导入
        """
        try:
            logger.info(f"Importing socket connections for item {item_uuid}, total sids: {len(connections)}")

            token = None
            if daemon_id:
                token = self.get_token(daemon_id, item_uuid)
            else:
                _, token = self.get_token_by_item(item_uuid)
            
            if not token:
                logger.warning(f"No token found for item {item_uuid}")
                return False

            self.connections[item_uuid] = {}

            for sid, conn_info in connections.items():
                user_uuid = conn_info.get('user_uuid', 'unknown')
                ip_address = conn_info.get('ip', 'unknown')

                logger.info(f"Processing sid {sid}, user: {user_uuid}, ip: {ip_address}")

                self.connections[item_uuid][sid] = {
                    'user_uuid': user_uuid,
                    'ip': ip_address
                }

                socket = self.get_socket(item_uuid, user_uuid)
                if not socket or not socket.is_connected():
                    self.create_socket(item_uuid, token, daemon_url, user_uuid, api_key, ip_address, sid)

            self._print_connection_tables(f"Imported Socket Connections for Item {item_uuid}")
            return True
        except Exception as e:
            logger.error(f"Failed to import socket connections: {str(e)}")
            return False

    def get_connections_by_ip(self, item_uuid: str, ip_address: str) -> list[dict[str, str]]:
        """
        根据IP地址获取连接信息（用于单播）
        """
        result = []
        if item_uuid in self.connections:
            for sid, conn_info in self.connections[item_uuid].items():
                if conn_info.get('ip') == ip_address:
                    result.append({
                        'sid': sid,
                        'user_uuid': conn_info.get('user_uuid'),
                        'ip': conn_info.get('ip')
                    })
        return result

    def get_all_connections_for_broadcast(self, item_uuid: str) -> list[dict[str, str]]:
        """
        获取项目的所有连接信息（用于广播）
        """
        result = []
        if item_uuid in self.connections:
            for sid, conn_info in self.connections[item_uuid].items():
                result.append({
                    'sid': sid,
                    'user_uuid': conn_info.get('user_uuid'),
                    'ip': conn_info.get('ip')
                })
        return result

    def update_connections_from_daemon(self, item_uuid: str, connections: dict[str, Any]) -> bool:
        """
        从daemon返回的连接池更新本地连接表
        
        Args:
            item_uuid: 项目UUID
            connections: daemon返回的连接表 {sid: {user_uuid, ip}}
            
        Returns:
            是否成功更新
        """
        with self.lock:
            self.connections[item_uuid] = {}
            for sid, conn_info in connections.items():
                self.connections[item_uuid][sid] = {
                    'user_uuid': conn_info.get('user_uuid', 'unknown'),
                    'ip': conn_info.get('ip', 'unknown')
                }
            self._print_connection_tables(f"Updated Connections for Item {item_uuid}")
            return True
