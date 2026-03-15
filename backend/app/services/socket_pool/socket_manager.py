from typing import Dict, Optional, List, Callable, Any
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
        self.tokens: Dict[str, TokenInfo] = {}  # item_uuid → token
        
        # 用户-项目映射：user_uuid → Set[item_uuid]
        self.user_item_map: Dict[str, set] = {}  # 权限校验专用
        
        # 项目-用户-连接映射：item_uuid → {user_uuid: socket连接实例}
        self.item_user_conn_map: Dict[str, Dict[str, ItemSocket]] = {}  # 断开连接专用
        
        # 用户-IP映射：user_uuid → ip_address
        self.user_ip_map: Dict[str, str] = {}  # 用户IP映射表
        
        # 项目-用户-IP映射：item_uuid → {user_uuid: ip_address}
        self.item_user_ip_map: Dict[str, Dict[str, str]] = {}  # 项目-用户-IP映射表

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
        
        # 更新用户-项目映射
        if user_uuid not in self.user_item_map:
            self.user_item_map[user_uuid] = set()
        self.user_item_map[user_uuid].add(item_uuid)
        
        # 更新项目-用户-连接映射
        if item_uuid not in self.item_user_conn_map:
            self.item_user_conn_map[item_uuid] = {}
        self.item_user_conn_map[item_uuid][user_uuid] = socket
        
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
            
            # 更新用户-项目映射
            if user_uuid in self.user_item_map:
                self.user_item_map[user_uuid].discard(item_uuid)
                # 如果用户没有任何项目了，移除该用户
                if not self.user_item_map[user_uuid]:
                    self.user_item_map.pop(user_uuid)
            
            # 更新项目-用户-连接映射
            if item_uuid in self.item_user_conn_map:
                if user_uuid in self.item_user_conn_map[item_uuid]:
                    self.item_user_conn_map[item_uuid].pop(user_uuid)
                # 如果项目没有任何用户了，移除该项目
                if not self.item_user_conn_map[item_uuid]:
                    self.item_user_conn_map.pop(item_uuid)
            
            # 更新项目-用户-IP映射
            if item_uuid in self.item_user_ip_map:
                if user_uuid in self.item_user_ip_map[item_uuid]:
                    self.item_user_ip_map[item_uuid].pop(user_uuid)
                # 如果项目没有任何用户IP映射了，移除该项目
                if not self.item_user_ip_map[item_uuid]:
                    self.item_user_ip_map.pop(item_uuid)
            
            # 更新用户-IP映射
            if user_uuid in self.user_ip_map:
                # 检查该用户是否还有其他项目
                if user_uuid not in self.user_item_map or item_uuid not in self.user_item_map[user_uuid]:
                    self.user_ip_map.pop(user_uuid)
    
    def remove_all_sockets_by_item(self, item_uuid: str):
        """
        移除并关闭指定Item的所有Socket连接
        """
        keys_to_remove = [(user_uuid, iid) for (user_uuid, iid), sock in self.sockets.items() if iid == item_uuid]
        
        # 记录要更新的用户
        affected_users = set()
        for user_uuid, iid in keys_to_remove:
            affected_users.add(user_uuid)
        
        # 移除socket连接
        for key in keys_to_remove:
            socket = self.sockets.pop(key)
            socket.disconnect()
        
        # 更新用户-项目映射
        for user_uuid in affected_users:
            if user_uuid in self.user_item_map:
                self.user_item_map[user_uuid].discard(item_uuid)
                # 如果用户没有任何项目了，移除该用户
                if not self.user_item_map[user_uuid]:
                    self.user_item_map.pop(user_uuid)
        
        # 更新项目-用户-连接映射
        if item_uuid in self.item_user_conn_map:
            self.item_user_conn_map.pop(item_uuid)
        
        # 更新项目-用户-IP映射
        if item_uuid in self.item_user_ip_map:
            # 记录所有受影响的用户
            users_to_check = list(self.item_user_ip_map[item_uuid].keys())
            # 移除该项目的所有用户IP映射
            self.item_user_ip_map.pop(item_uuid)
            
            # 更新用户-IP映射
            for user_uuid in users_to_check:
                # 检查用户是否还有其他项目
                if user_uuid not in self.user_item_map or item_uuid not in self.user_item_map[user_uuid]:
                    if user_uuid in self.user_ip_map:
                        self.user_ip_map.pop(user_uuid)

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
    
    def get_connection_tables(self) -> Dict[str, Any]:
        """
        获取所有连接表
        
        Returns:
            包含用户-项目映射、项目-用户连接映射、用户-IP映射和项目-Token映射的字典
        """
        # 转换用户-项目映射为列表格式以便JSON序列化
        user_item_map = {user_uuid: list(items) for user_uuid, items in self.user_item_map.items()}
        
        # 转换项目-用户连接映射，包含IP信息
        item_user_conn_map = {}
        for item_uuid, user_conns in self.item_user_conn_map.items():
            item_user_conn_map[item_uuid] = {}
            
            for user_uuid, conn in user_conns.items():
                # 获取用户IP
                ip_address = self.item_user_ip_map.get(item_uuid, {}).get(user_uuid, 'unknown')
                
                item_user_conn_map[item_uuid][user_uuid] = {
                    'is_connected': conn.is_connected(),
                    'status': conn.status.value,
                    'ip': ip_address
                }
        
        # 转换Token映射
        item_token_map = {item_uuid: token_info.token for item_uuid, token_info in self.tokens.items()}
        
        # 用户-IP映射
        user_ip_map = self.user_ip_map.copy()
        
        return {
            'user_item_map': user_item_map,
            'item_user_conn_map': item_user_conn_map,
            'item_token_map': item_token_map,
            'user_ip_map': user_ip_map
        }
    
    def disconnect_user_from_item(self, item_uuid: str, user_uuid: str) -> bool:
        """
        断开特定用户与特定项目的Socket连接
        
        Args:
            item_uuid: 项目UUID
            user_uuid: 用户UUID
            
        Returns:
            是否成功断开连接
        """
        try:
            # 使用remove_socket方法来断开连接（会自动更新所有映射）
            self.remove_socket(item_uuid, user_uuid)
            return True
        except Exception:
            return False
    
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
            (user_uuid, iid) for (user_uuid, iid), sock in self.sockets.items()
            if sock.get_status() == TerminalStatus.STOPPED
        ]
        for user_uuid, item_uuid in disconnected_items:
            self.remove_socket(item_uuid, user_uuid)
            
    def import_socket_connections(self, item_uuid: str, connections: Dict[str, Any], daemon_url: str, api_key: str) -> bool:
        """
        从daemon导入socket连接表
        
        Args:
            item_uuid: 项目UUID
            connections: daemon返回的连接表，格式为 {user_uuid: socket_info}
            daemon_url: daemon的URL
            api_key: API密钥
            
        Returns:
            是否成功导入
        """
        try:
            for user_uuid, socket_info in connections.items():
                token = socket_info.get("token")
                if not token:
                    continue
                    
                # 获取IP地址信息
                ip_address = socket_info.get("ip", "unknown")
                    
                # 获取或创建socket连接
                socket = self.get_or_create_socket(item_uuid, token, daemon_url, user_uuid, api_key)
                if not socket.is_connected():
                    continue
                    
                # 更新IP映射表
                # 更新用户-IP映射
                self.user_ip_map[user_uuid] = ip_address
                
                # 更新项目-用户-IP映射
                if item_uuid not in self.item_user_ip_map:
                    self.item_user_ip_map[item_uuid] = {}
                self.item_user_ip_map[item_uuid][user_uuid] = ip_address
                    
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to import socket connections: {str(e)}")
            return False
