from enum import Enum
from typing import Dict, Any
from datetime import datetime


class TerminalStatus(str, Enum):
    """
    终端状态枚举
    """
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    ERROR = "error"


class TokenInfo:
    """
    Token信息类
    """
    def __init__(self, item_uuid: str, token: str, expire_time: datetime):
        self.item_uuid = item_uuid
        self.token = token
        self.expire_time = expire_time

    def is_expired(self) -> bool:
        """
        检查Token是否过期
        """
        return datetime.now() > self.expire_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_uuid": self.item_uuid,
            "token": self.token,
            "expire_time": self.expire_time.isoformat()
        }
