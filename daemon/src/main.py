import os
import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core import config
from utils import logger
from api import router, sio
from service import terminal_manager

# 创建FastAPI应用
fastapi_app = FastAPI(
    title="TermPaws Daemon",
    description="Terminal Management Daemon API",
    version="0.1.0"
)

# 配置CORS
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@fastapi_app.get("/")
def root():
    """
    Daemon健康检查接口
    """
    return {
        "message": "TermPaws Daemon is running",
        "version": "0.1.0"
    }

# 注册HTTP路由
fastapi_app.include_router(router, prefix="/api")

# 创建WSGI应用，将Socket.IO和FastAPI结合
app = socketio.ASGIApp(sio, fastapi_app)


if __name__ == "__main__":
    # 获取配置
    host = config.get("HOST")
    port = config.get("PORT")
    
    logger.info(f"Starting TermPaws Daemon on {host}:{port}")
    logger.info(f"API Key: {'***' + config.get('API_KEY')[-4:] if config.get('API_KEY') else 'Not set'}")
    
    # 启动服务器
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
