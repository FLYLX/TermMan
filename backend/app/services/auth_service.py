import uuid
import hashlib
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class AuthService:
    """
    鉴权服务
    """
    def __init__(self):
        self.api_keys: Dict[str, Dict[str, Any]] = {}
        self.tokens: Dict[str, Dict[str, Any]] = {}

    def generate_api_key(self, daemon_id: str) -> str:
        """
        生成API Key
        """
        api_key = hashlib.sha256(f"{daemon_id}-{uuid.uuid4()}-{datetime.now()}".encode()).hexdigest()
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
        if api_key in self.api_keys:
            self.api_keys[api_key]["last_used"] = datetime.now()
            return self.api_keys[api_key]["daemon_id"]
        return None

    def revoke_api_key(self, api_key: str) -> bool:
        """
        撤销API Key
        """
        if api_key in self.api_keys:
            del self.api_keys[api_key]
            return True
        return False

    def generate_token(self, item_uuid: str, expire_minutes: int = 1440) -> str:
        """
        生成访问Token
        """
        token = str(uuid.uuid4())
        expire_time = datetime.now() + timedelta(minutes=expire_minutes)
        self.tokens[token] = {
            "item_uuid": item_uuid,
            "created_at": datetime.now(),
            "expire_time": expire_time
        }
        return token

    def validate_token(self, token: str) -> Optional[str]:
        """
        验证Token有效性
        """
        if token not in self.tokens:
            return None

        token_info = self.tokens[token]
        if datetime.now() > token_info["expire_time"]:
            del self.tokens[token]
            return None

        return token_info["item_uuid"]

    def revoke_token(self, token: str) -> bool:
        """
        撤销Token
        """
        if token in self.tokens:
            del self.tokens[token]
            return True
        return False

    def refresh_token(self, token: str, extend_minutes: int = 60) -> Optional[str]:
        """
        刷新Token有效期
        """
        item_uuid = self.validate_token(token)
        if not item_uuid:
            return None

        # 撤销旧token
        self.revoke_token(token)
        # 生成新token
        return self.generate_token(item_uuid, extend_minutes)

    def get_mission_passport(self, daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """
        获取任务通行证（MCSM missionPassport）
        """
        passport = {
            "daemon_id": daemon_id,
            "item_uuid": item_uuid,
            "token": self.generate_token(item_uuid),
            "timestamp": int(datetime.now().timestamp() * 1000),
            "expire_time": int((datetime.now() + timedelta(hours=24)).timestamp() * 1000)
        }
        return passport

    def verify_mission_passport(self, passport: Dict[str, Any]) -> bool:
        """
        验证任务通行证
        """
        token = passport.get("token")
        item_uuid = passport.get("item_uuid")
        if not token or not item_uuid:
            return False

        validated_item_uuid = self.validate_token(token)
        return validated_item_uuid == item_uuid
