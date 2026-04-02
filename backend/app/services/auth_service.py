import secrets
import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import threading
import logging

logger = logging.getLogger(__name__)


class AuthService:
    """
    鉴权服务 - 按 UPDATE.MD 规范实现
    
    凭证类型：
    1. 用户Token：JWT格式，由FastAPI security模块处理
    2. 终端临时Token：随机字符串(32位)，短期有效(<10分钟)，一次性使用
    3. Daemon认证Token：随机字符串(64位)，用于Daemon向Backend认证
    4. API_KEY：Daemon唯一标识，预配置
    
    存储结构：
    - terminal_temp_tokens: {token -> {item_uuid, user_id, expire_at, used}}
    - daemon_auth_tokens: {token -> {api_key, expire_at}}
    """
    
    DEFAULT_TERMINAL_TOKEN_EXPIRE_MINUTES = 10
    DEFAULT_DAEMON_AUTH_TOKEN_EXPIRE_MINUTES = 30
    
    def __init__(self):
        self._lock = threading.RLock()
        
        self.terminal_temp_tokens: Dict[str, Dict[str, Any]] = {}
        
        self.daemon_auth_tokens: Dict[str, Dict[str, Any]] = {}
        
        self.api_keys: Dict[str, Dict[str, Any]] = {}
        
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        def cleanup():
            while True:
                threading.Event().wait(60)
                self._cleanup_expired_tokens()
        
        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()
    
    def _cleanup_expired_tokens(self):
        now = datetime.now()
        with self._lock:
            expired_terminal = [
                token for token, info in self.terminal_temp_tokens.items()
                if now > info.get("expire_at", now)
            ]
            for token in expired_terminal:
                del self.terminal_temp_tokens[token]
                logger.debug(f"Cleaned up expired terminal token")
            
            expired_daemon = [
                token for token, info in self.daemon_auth_tokens.items()
                if now > info.get("expire_at", now)
            ]
            for token in expired_daemon:
                del self.daemon_auth_tokens[token]
                logger.debug(f"Cleaned up expired daemon auth token")
    
    def generate_terminal_temp_token(
        self, 
        item_uuid: str, 
        user_id: str,
        expire_minutes: int = None
    ) -> Dict[str, Any]:
        """
        生成终端临时Token
        
        Args:
            item_uuid: 项目UUID
            user_id: 用户ID
            expire_minutes: 过期时间(分钟)，默认10分钟
            
        Returns:
            包含token和过期时间的字典
        """
        if expire_minutes is None:
            expire_minutes = self.DEFAULT_TERMINAL_TOKEN_EXPIRE_MINUTES
        
        token = secrets.token_hex(16)
        expire_at = datetime.now() + timedelta(minutes=expire_minutes)
        
        with self._lock:
            self.terminal_temp_tokens[token] = {
                "item_uuid": item_uuid,
                "user_id": user_id,
                "expire_at": expire_at,
                "used": False,
                "created_at": datetime.now()
            }
        
        logger.info(f"Generated terminal temp token for item={item_uuid}, user={user_id}, expires_in={expire_minutes}min")
        
        return {
            "token": token,
            "item_uuid": item_uuid,
            "user_id": user_id,
            "expire_at": expire_at.isoformat(),
            "expires_in": expire_minutes * 60
        }
    
    def validate_terminal_temp_token(
        self, 
        token: str, 
        item_uuid: str,
        mark_used: bool = True
    ) -> Dict[str, Any]:
        """
        验证终端临时Token
        
        Args:
            token: Token字符串
            item_uuid: 项目UUID
            mark_used: 是否标记为已使用（一次性Token）
            
        Returns:
            验证结果 {success, user_id, error}
        """
        with self._lock:
            if token not in self.terminal_temp_tokens:
                logger.warning(f"Terminal token not found: {token[:8]}...")
                return {"success": False, "error": "Token not found"}
            
            token_info = self.terminal_temp_tokens[token]
            
            if token_info["item_uuid"] != item_uuid:
                logger.warning(f"Token item_uuid mismatch: expected={item_uuid}, got={token_info['item_uuid']}")
                return {"success": False, "error": "Token item_uuid mismatch"}
            
            if datetime.now() > token_info["expire_at"]:
                del self.terminal_temp_tokens[token]
                logger.warning(f"Terminal token expired: {token[:8]}...")
                return {"success": False, "error": "Token expired"}
            
            if token_info["used"]:
                logger.warning(f"Terminal token already used (potential replay attack): {token[:8]}...")
                return {"success": False, "error": "Token already used"}
            
            user_id = token_info["user_id"]
            
            if mark_used:
                token_info["used"] = True
                logger.info(f"Terminal token validated and marked as used: item={item_uuid}, user={user_id}")
            
            return {
                "success": True,
                "user_id": user_id,
                "item_uuid": item_uuid
            }
    
    def revoke_terminal_temp_token(self, token: str) -> bool:
        """
        撤销终端临时Token
        """
        with self._lock:
            if token in self.terminal_temp_tokens:
                del self.terminal_temp_tokens[token]
                logger.info(f"Revoked terminal temp token: {token[:8]}...")
                return True
            return False
    
    def generate_daemon_auth_token(
        self, 
        api_key: str,
        expire_minutes: int = None
    ) -> Dict[str, Any]:
        """
        生成Daemon认证Token
        
        Daemon启动后向Backend认证时使用
        
        Args:
            api_key: Daemon的API_KEY
            expire_minutes: 过期时间(分钟)，默认30分钟
            
        Returns:
            包含token和过期时间的字典
        """
        if expire_minutes is None:
            expire_minutes = self.DEFAULT_DAEMON_AUTH_TOKEN_EXPIRE_MINUTES
        
        token = secrets.token_hex(32)
        expire_at = datetime.now() + timedelta(minutes=expire_minutes)
        
        with self._lock:
            self.daemon_auth_tokens[token] = {
                "api_key": api_key,
                "expire_at": expire_at,
                "created_at": datetime.now()
            }
        
        logger.info(f"Generated daemon auth token for api_key=***{api_key[-4:]}, expires_in={expire_minutes}min")
        
        return {
            "token": token,
            "expire_at": expire_at.isoformat(),
            "expires_in": expire_minutes * 60
        }
    
    def validate_daemon_auth_token(self, token: str) -> Dict[str, Any]:
        """
        验证Daemon认证Token
        
        Args:
            token: Token字符串
            
        Returns:
            验证结果 {success, api_key, error}
        """
        with self._lock:
            if token not in self.daemon_auth_tokens:
                return {"success": False, "error": "Token not found"}
            
            token_info = self.daemon_auth_tokens[token]
            
            if datetime.now() > token_info["expire_at"]:
                del self.daemon_auth_tokens[token]
                return {"success": False, "error": "Token expired"}
            
            return {
                "success": True,
                "api_key": token_info["api_key"]
            }
    
    def consume_daemon_auth_token(self, token: str) -> Dict[str, Any]:
        """
        消费Daemon认证Token（主连接建立后调用）
        
        Args:
            token: Token字符串
            
        Returns:
            验证结果 {success, api_key, error}
        """
        result = self.validate_daemon_auth_token(token)
        if result["success"]:
            with self._lock:
                if token in self.daemon_auth_tokens:
                    del self.daemon_auth_tokens[token]
                    logger.info(f"Consumed daemon auth token: {token[:8]}...")
        return result
    
    def generate_access_token(
        self, 
        item_uuid: str, 
        user_id: str,
        secret_key: str,
        expire_seconds: int = 600
    ) -> str:
        """
        生成浏览器访问Token（用于直连Daemon）
        
        格式：item_uuid:user_uuid:timestamp:expires_in:signature
        
        Args:
            item_uuid: 项目UUID
            user_id: 用户ID
            secret_key: 签名密钥
            expire_seconds: 过期时间(秒)，默认10分钟
            
        Returns:
            签名Token字符串
        """
        timestamp = int(time.time())
        
        payload = f"{item_uuid}:{user_id}:{timestamp}:{expire_seconds}"
        
        signature = hmac.new(
            secret_key.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:32]
        
        token = f"{payload}:{signature}"
        
        logger.info(f"Generated access token for item={item_uuid}, user={user_id}")
        
        return token
    
    def verify_access_token(
        self, 
        token: str, 
        item_uuid: str,
        secret_key: str
    ) -> Dict[str, Any]:
        """
        验证浏览器访问Token
        
        Args:
            token: Token字符串
            item_uuid: 项目UUID
            secret_key: 签名密钥
            
        Returns:
            验证结果 {success, user_id, error}
        """
        try:
            parts = token.split(":")
            if len(parts) != 5:
                return {"success": False, "error": "Invalid token format"}
            
            token_item_uuid, user_id, timestamp, expires_in, signature = parts
            timestamp = int(timestamp)
            expires_in = int(expires_in)
            
            if token_item_uuid != item_uuid:
                return {"success": False, "error": "Token item_uuid mismatch"}
            
            current_time = int(time.time())
            if current_time > timestamp + expires_in:
                return {"success": False, "error": "Token expired"}
            
            payload = f"{token_item_uuid}:{user_id}:{timestamp}:{expires_in}"
            expected_signature = hmac.new(
                secret_key.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()[:32]
            
            if signature != expected_signature:
                return {"success": False, "error": "Invalid signature"}
            
            return {
                "success": True,
                "user_id": user_id,
                "item_uuid": item_uuid
            }
            
        except Exception as e:
            logger.error(f"Error verifying access token: {e}")
            return {"success": False, "error": str(e)}
    
    def generate_api_key(self, daemon_id: str) -> str:
        """
        生成API Key
        """
        api_key = secrets.token_hex(32)
        with self._lock:
            self.api_keys[api_key] = {
                "daemon_id": daemon_id,
                "created_at": datetime.now(),
                "last_used": None
            }
        return api_key
    
    def validate_api_key(self, api_key: str) -> Optional[str]:
        """
        验证API Key有效性
        """
        with self._lock:
            if api_key in self.api_keys:
                self.api_keys[api_key]["last_used"] = datetime.now()
                return self.api_keys[api_key]["daemon_id"]
        return None
    
    def revoke_api_key(self, api_key: str) -> bool:
        """
        撤销API Key
        """
        with self._lock:
            if api_key in self.api_keys:
                del self.api_keys[api_key]
                return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取认证服务统计信息
        """
        with self._lock:
            return {
                "terminal_temp_tokens": len(self.terminal_temp_tokens),
                "daemon_auth_tokens": len(self.daemon_auth_tokens),
                "api_keys": len(self.api_keys)
            }


auth_service = AuthService()
