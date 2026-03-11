import uuid
from typing import Optional
from core import memory_store, config
from utils.logger import logger


class AuthService:
    """
    鉴权服务类
    """
    def __init__(self):
        self.api_key = config.get("API_KEY")

    def validate_api_key(self, api_key: str) -> bool:
        """
        验证API Key
        """
        if not self.api_key or not api_key:
            return False
        return self.api_key == api_key

    def generate_terminal_token(self, item_uuid: str) -> str:
        """
        生成终端Token
        """
        token = str(uuid.uuid4())
        # 存储token到内存，有效期1天
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


# 创建全局鉴权服务实例
auth_service = AuthService()
