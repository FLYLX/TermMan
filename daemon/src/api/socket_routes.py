import socketio
from service.socket_service import SocketService

# 创建Socket.IO服务器实例（使用async_mode="asgi"）
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")

# 创建Socket服务实例
socket_service = SocketService(sio)

# 存储到全局实例
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import set_socket_service
set_socket_service(socket_service)

