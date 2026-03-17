from enum import Enum
from typing import Dict, Any


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"


class DaemonConfig:
    def __init__(self, ip: str, port: int, api_key: str):
        self.ip = ip
        self.port = port
        self.api_key = api_key
        self.daemon_id = f"{ip}:{port}:{api_key}"
        self.base_url = f"http://{ip}:{port}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "daemon_id": self.daemon_id,
            "ip": self.ip,
            "port": self.port,
            "base_url": self.base_url
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DaemonConfig":
        return cls(
            ip=data["ip"],
            port=data["port"],
            api_key=data["api_key"]
        )
