import json
from typing import Any, Dict


class ProtocolCodec:
    """
    MCSM协议数据编解码
    """
    @staticmethod
    def encode(data: Any) -> str:
        """
        编码数据为JSON字符串
        """
        try:
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return ""

    @staticmethod
    def decode(data: str) -> Dict[str, Any]:
        """
        解码JSON字符串为数据
        """
        try:
            return json.loads(data)
        except Exception:
            return {}

    @staticmethod
    def wrap_data(event: str, data: Any) -> Dict[str, Any]:
        """
        包装数据为MCSM协议格式
        """
        return {
            "event": event,
            "data": data,
            "timestamp": ProtocolCodec.get_timestamp()
        }

    @staticmethod
    def unwrap_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析MCSM协议格式数据
        """
        return raw_data.get("data", {})

    @staticmethod
    def get_timestamp() -> int:
        """
        获取当前时间戳（毫秒）
        """
        import time
        return int(time.time() * 1000)
