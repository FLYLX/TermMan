from enum import Enum


class ProtocolEvents(str, Enum):
    """
    MCSM协议事件枚举
    """
    # 数据流事件
    STREAM = "stream"
    WRITE = "write"
    
    # 实例事件
    INSTANCE_STDOUT = "instance/stdout"
    INSTANCE_STDERR = "instance/stderr"
    INSTANCE_EXIT = "instance/exit"
    
    # 终端控制事件
    TERMINAL_START = "terminal/start"
    TERMINAL_STOP = "terminal/stop"
    TERMINAL_STATUS = "terminal/status"
    
    # 管理事件
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    AUTH = "auth"
    AUTH_ACK = "auth_ack"
