from typing import Dict, Optional, List, Callable
from datetime import datetime, timedelta
from .item_socket import ItemSocket
from .socket_models import TerminalStatus, TokenInfo
from ..protocol import ProtocolEvents


class SocketManager:
    """
    Item Socket池管理
    """
    def __init__(self):
        self.sockets: Dict[tuple, ItemSocket] = {}  # 使用(user_uuid, item_uuid)作为键
        self.tokens: Dict[str, TokenInfo] = {}

    def get_socket(self, item_uuid: str, user_uuid: str) -> Optional[ItemSocket]:
        """
        获取指定用户和Item的Socket连接
        """
        return self.sockets.get((user_uuid, item_uuid))
    
    def get_sockets_by_item(self, item_uuid: str) -> List[ItemSocket]:
        """
        获取指定Item的所有Socket连接
        """
        return [sock for (uuid, iid), sock in self.sockets.items() if iid == item_uuid]

    def create_socket(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str, api_key: Optional[str] = None) -> ItemSocket:
        """
        创建新的Item Socket连接
        """
        socket = ItemSocket(item_uuid, token, daemon_url, user_uuid)
        self.sockets[(user_uuid, item_uuid)] = socket
        if api_key:
            socket.connect(api_key)
        return socket

    def get_or_create_socket(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str, api_key: Optional[str] = None) -> ItemSocket:
        """
        获取或创建Item Socket连接
        """
        socket = self.get_socket(item_uuid, user_uuid)
        if not socket or not socket.is_connected():
            socket = self.create_socket(item_uuid, token, daemon_url, user_uuid, api_key)
        return socket

    def remove_socket(self, item_uuid: str, user_uuid: str):
        """
        移除并关闭Item Socket连接
        """
        key = (user_uuid, item_uuid)
        if key in self.sockets:
            socket = self.sockets.pop(key)
            socket.disconnect()
    
    def remove_all_sockets_by_item(self, item_uuid: str):
        """
        移除并关闭指定Item的所有Socket连接
        """
        keys_to_remove = [(user_uuid, iid) for (user_uuid, iid), sock in self.sockets.items() if iid == item_uuid]
        for key in keys_to_remove:
            socket = self.sockets.pop(key)
            socket.disconnect()

    def add_token(self, item_uuid: str, token: str, expire_minutes: int = 1440) -> TokenInfo:
        """
        添加Token信息
        """
        expire_time = datetime.now() + timedelta(minutes=expire_minutes)
        token_info = TokenInfo(item_uuid, token, expire_time)
        self.tokens[item_uuid] = token_info
        return token_info

    def get_token(self, item_uuid: str) -> Optional[TokenInfo]:
        """
        获取Token信息
        """
        token_info = self.tokens.get(item_uuid)
        if token_info and token_info.is_expired():
            self.tokens.pop(item_uuid)
            return None
        return token_info

    def validate_token(self, item_uuid: str, token: str) -> bool:
        """
        验证Token有效性
        """
        token_info = self.get_token(item_uuid)
        return token_info is not None and token_info.token == token

    def get_all_sockets(self) -> List[ItemSocket]:
        """
        获取所有Socket连接
        """
        return list(self.sockets.values())

    def get_running_sockets(self) -> List[ItemSocket]:
        """
        获取所有运行中的Socket连接
        """
        return [sock for sock in self.sockets.values() if sock.is_connected()]
    
    def get_user_sockets(self, user_uuid: str) -> List[ItemSocket]:
        """
        获取指定用户的所有Socket连接
        """
        return [sock for (uuid, iid), sock in self.sockets.items() if uuid == user_uuid]
    
    def register_stream_callback(self, item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        """
        注册终端输出回调
        """
        socket = self.get_socket(item_uuid, user_uuid)
        if socket and socket.is_connected():
            socket.on(ProtocolEvents.STREAM, callback)
            return True
        return False

    def cleanup_expired_tokens(self):
        """
        清理过期的Token
        """
        expired_items = [
            item_uuid for item_uuid, token_info in self.tokens.items()
            if token_info.is_expired()
        ]
        for item_uuid in expired_items:
            self.tokens.pop(item_uuid)

    def cleanup_disconnected_sockets(self):
        """
        清理断开的Socket连接
        """
        disconnected_items = [
            item_uuid for item_uuid, sock in self.sockets.items()
            if sock.get_status() == TerminalStatus.STOPPED
        ]
        for item_uuid in disconnected_items:
            self.remove_socket(item_uuid)
