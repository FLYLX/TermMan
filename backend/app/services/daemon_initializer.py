"""
Daemon连接初始化模块
负责在应用启动时初始化所有daemon连接

按 pool.md 规范：
- ConnectionManager: 管理 Backend → Daemon 的主连接（管控指令）
- backend_conn_pool: 全局连接池单例，追踪 Daemon 主连接状态
"""

import logging
from datetime import datetime

from sqlmodel import Session

from app.core.db import engine
from app.models import Item, ItemStatus
from app.services.connection_pool import ConnectionManager, DaemonConfig, backend_conn_pool
from app.services.socket_pool import SocketManager

logger = logging.getLogger(__name__)

connection_manager = ConnectionManager()
socket_manager = SocketManager()


def handle_connection_update(data: dict):
    """
    处理来自daemon的连接池更新
    
    Args:
        data: 包含type和connections的字典
            - type: "full_sync" 或 "item_update"
            - connections: 连接池数据
            - rooms: Room信息
    """
    update_type = data.get("type")
    rooms = data.get("rooms", {})
    
    logger.info(f"\n{'*'*80}")
    logger.info(f"[Backend] 收到 Daemon 连接池同步通知")
    logger.info(f"{'*'*80}")
    logger.info(f"  同步类型: {update_type}")
    logger.info(f"  Rooms 数量: {len(rooms)}")
    
    if rooms:
        for room_id, room_info in rooms.items():
            logger.info(f"    Room: {room_id}")
            logger.info(f"      - permanent: {room_info.get('permanent_count', 0)}")
            logger.info(f"      - temporary: {room_info.get('temporary_count', 0)}")
    
    logger.info(f"{'*'*80}\n")


def initialize_daemon_connections():
    """
    初始化daemon连接的主要函数：
    1. 检索所有item
    2. 提取不重复的ip:port:api_key组合
    3. 为每个daemon创建WebSocket连接
    4. 将连接添加到连接池
    5. 设置连接更新回调
    6. 更新 backend_conn_pool 中的 daemon_main_conn_state
    """
    logger.info("Starting up application and initializing daemon connections...")

    with Session(engine) as session:
        items = session.query(Item).all()
        logger.info(f"Found {len(items)} items in database")

        unique_configs: dict[str, dict] = {}

        for item in items:
            if item.socket_host and item.socket_port and item.api_key:
                unique_key = f"{item.socket_host}:{item.socket_port}:{item.api_key}"

                if unique_key not in unique_configs:
                    unique_configs[unique_key] = {
                        "host": item.socket_host,
                        "port": item.socket_port,
                        "api_key": item.api_key,
                        "items": [item],
                    }
                else:
                    unique_configs[unique_key]["items"].append(item)

        logger.info(f"Found {len(unique_configs)} unique daemon configurations")

        for _unique_key, config in unique_configs.items():
            host = config["host"]
            port = config["port"]
            api_key = config["api_key"]
            items_list = config["items"]

            daemon_config = DaemonConfig(ip=host, port=port, api_key=api_key)

            try:
                connection = connection_manager.get_or_create_connection(daemon_config)
                
                connection.on("connection_update", handle_connection_update)

                if connection.is_connected():
                    logger.info(f"Successfully connected to daemon at {host}:{port}")
                    
                    daemon_state = backend_conn_pool.create_daemon_main_conn_state(
                        api_key, 
                        daemon_config.base_url
                    )
                    daemon_state.set_connected()

                    with Session(engine) as update_session:
                        for item in items_list:
                            update_item = update_session.get(Item, item.id)
                            if update_item:
                                update_item.status = ItemStatus.stopped
                                update_item.socket_connected = True
                                update_item.socket_last_connected = datetime.now()
                        update_session.commit()
                else:
                    logger.error(f"Failed to connect to daemon at {host}:{port}")
                    _mark_items_disconnected(items_list)

            except Exception as e:
                logger.error(f"Error connecting to daemon at {host}:{port}: {str(e)}")
                _mark_items_disconnected(items_list)

    logger.info("Daemon initialization completed")


def _mark_items_disconnected(items: list[Item]):
    """标记items为断开状态"""
    with Session(engine) as update_session:
        for item in items:
            update_item = update_session.get(Item, item.id)
            if update_item:
                update_item.status = ItemStatus.stopped
                update_item.socket_connected = False
        update_session.commit()


if __name__ == "__main__":
    initialize_daemon_connections()
