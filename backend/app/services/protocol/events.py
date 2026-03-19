from enum import Enum


class ProtocolEvents(str, Enum):
    STREAM = "stream"
    WRITE = "terminal/write"
    
    TERMINAL_START = "terminal/start"
    TERMINAL_STOP = "terminal/stop"
    TERMINAL_STATUS = "terminal/status"
    
    TERMINAL_CONNECT = "terminal/connect"
