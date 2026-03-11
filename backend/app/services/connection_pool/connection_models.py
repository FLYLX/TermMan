from enum import Enum
from typing import Dict, Any


class ConnectionStatus(str, Enum):
    """
    连接状态枚举
    """
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"


class DaemonConfig:
    """
    Daemon节点配置类
    """
    def __init__(self, daemon_id: str, ip: str, port: int, api_key: str):
        self.daemon_id = daemon_id
        self.ip = ip
        self.port = port
        self.api_key = api_key
        self.base_url = f"http://{ip}:{port}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "daemon_id": self.daemon_id,
            "ip": self.ip,
            "port": self.port,
            "base_url": self.base_url
        }
