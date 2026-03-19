import uuid
import hmac
import hashlib
import time
from typing import Optional, Dict, Any
from core import memory_store, config
from utils.logger import logger


class AuthService:
    """
    鉴权服务类 - 按 UPDATE.MD 规范实现
    
    核心职责：
    1. API Key 验证（Backend连接认证）
    2. 终端Token管理（Daemon内部使用）
    3. 浏览器Access Token验证（与Backend共享密钥）
    """
    
    def __init__(self):
        self.api_key = config.get("API_KEY")
        self.secret_key = config.get("SECRET_KEY", "default-secret-key-change-in-production")

    def validate_api_key(self, api_key: str) -> bool:
        """
        验证API Key
        
        Backend连接Daemon时使用
        """
        if not self.api_key or not api_key:
            return False
        return self.api_key == api_key

    def generate_terminal_token(self, item_uuid: str) -> str:
        """
        生成终端Token
        
        Daemon内部使用，用于标识终端会话
        """
        token = str(uuid.uuid4())
        memory_store.set(f"terminal_token:{item_uuid}", token, ttl_minutes=1440)
        return token

    def validate_terminal_token(self, item_uuid: str, token: str) -> bool:
        """
        验证终端Token
        """
        stored_token = memory_store.get(f"terminal_token:{item_uuid}")
        if not stored_token:
            return False
        return stored_token == token

    def revoke_terminal_token(self, item_uuid: str) -> bool:
        """
        撤销终端Token
        """
        return memory_store.delete(f"terminal_token:{item_uuid}")

    def get_terminal_token(self, item_uuid: str) -> Optional[str]:
        """
        获取终端Token
        """
        return memory_store.get(f"terminal_token:{item_uuid}")

    def verify_access_token(self, access_token: str, item_uuid: str) -> Dict[str, Any]:
        """
        验证浏览器Access Token
        
        格式：item_uuid:user_uuid:timestamp:expires_in:signature
        
        Args:
            access_token: 浏览器携带的临时Token
            item_uuid: 请求的item_uuid
            
        Returns:
            验证结果 {success, user_uuid, error}
        """
        try:
            parts = access_token.split(":")
            if len(parts) != 5:
                logger.warning(f"Invalid token format: expected 5 parts, got {len(parts)}")
                return {"success": False, "error": "Invalid token format"}
            
            token_item_uuid, user_uuid, timestamp, expires_in, signature = parts
            timestamp = int(timestamp)
            expires_in = int(expires_in)
            
            if token_item_uuid != item_uuid:
                logger.warning(f"Token item_uuid mismatch: expected={item_uuid}, got={token_item_uuid}")
                return {"success": False, "error": "Token item_uuid mismatch"}
            
            current_time = int(time.time())
            if current_time > timestamp + expires_in:
                logger.warning(f"Token expired: current={current_time}, expire_at={timestamp + expires_in}")
                return {"success": False, "error": "Token expired"}
            
            payload = f"{token_item_uuid}:{user_uuid}:{timestamp}:{expires_in}"
            expected_signature = hmac.new(
                self.secret_key.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()[:32]
            
            if signature != expected_signature:
                logger.warning(f"Invalid signature: expected={expected_signature[:16]}..., got={signature[:16]}...")
                return {"success": False, "error": "Invalid signature"}
            
            logger.info(f"Access token verified: item={item_uuid}, user={user_uuid}")
            return {
                "success": True,
                "user_uuid": user_uuid,
                "item_uuid": item_uuid
            }
            
        except Exception as e:
            logger.error(f"Error verifying access token: {e}")
            return {"success": False, "error": str(e)}


auth_service = AuthService()
