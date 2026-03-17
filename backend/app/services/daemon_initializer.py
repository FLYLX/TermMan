"""
Daemon连接初始化模块
负责在应用启动时初始化所有daemon连接
"""

import logging
from datetime import datetime

from sqlmodel import Session

from app.core.db import engine
from app.models import Item, ItemStatus
from app.services.connection_pool import ConnectionManager, DaemonConfig
from app.services.socket_pool import SocketManager

logger = logging.getLogger(__name__)

connection_manager = ConnectionManager()

socket_manager = SocketManager()


def handle_connection_update(data):
    """
    处理来自daemon的连接池更新
    
    Args:
        data: 包含type和connections的字典
            - type: "full_sync" 或 "item_update"
            - connections: 连接池数据
    """
    update_type = data.get("type")
    connections = data.get("connections", {})
    
    logger.info(f"\n{'*'*80}")
    logger.info(f"[Backend] 收到 Daemon 连接池同步通知")
    logger.info(f"{'*'*80}")
    logger.info(f"  同步类型: {update_type}")
    
    if update_type == "full_sync":
        logger.info(f"  全量同步: {len(connections)} 个Items")
        
        for item_uuid, item_conns in connections.items():
            logger.info(f"    Item: {item_uuid}")
            if item_conns:
                for sid, conn_info in item_conns.items():
                    logger.info(f"      - SID: {sid[:16]}... | User: {conn_info.get('user_uuid', 'unknown')} | IP: {conn_info.get('ip', 'unknown')}")
            else:
                logger.info(f"      - 无连接")
        
        socket_manager.connections = connections
        socket_manager._print_connection_tables("全量同步自 Daemon")
        
    elif update_type == "item_update":
        item_uuid = data.get("item_uuid")
        item_connections = data.get("item_connections", {})
        
        if item_uuid:
            logger.info(f"  增量更新 Item: {item_uuid}")
            logger.info(f"  连接数: {len(item_connections)}")
            
            if item_connections:
                logger.info(f"  连接详情:")
                for sid, conn_info in item_connections.items():
                    logger.info(f"    - SID: {sid[:16]}... | User: {conn_info.get('user_uuid', 'unknown')} | IP: {conn_info.get('ip', 'unknown')}")
            else:
                logger.info(f"  连接详情: 无连接")
            
            socket_manager.connections[item_uuid] = item_connections
            socket_manager._print_connection_tables(f"增量更新: {item_uuid}")
    
    logger.info(f"{'*'*80}\n")


def initialize_daemon_connections():
    """
    初始化daemon连接的主要函数：
    1. 检索所有item
    2. 提取不重复的ip:port:api_key组合
    3. 为每个daemon创建WebSocket连接
    4. 将连接添加到连接池
    5. 设置连接更新回调
    """
    logger.info("Starting up application and initializing daemon connections...")

    with Session(engine) as session:
        items = session.query(Item).all()
        logger.info(f"Found {len(items)} items in database")

        unique_configs = {}

        for item in items:
            if item.socket_host and item.socket_port and item.api_key:
                unique_key = f"{item.socket_host}:{item.socket_port}:{item.api_key}"

                if unique_key not in unique_configs:
                    unique_configs[unique_key] = {
                        "host": item.socket_host,
                        "port": item.socket_port,
                        "api_key": item.api_key,
                        "endpoint": f"{item.socket_host}:{item.socket_port}",
                        "items": [item],
                    }
                else:
                    unique_configs[unique_key]["items"].append(item)

        logger.info(f"Found {len(unique_configs)} unique daemon configurations")

        for _unique_key, config in unique_configs.items():
            host = config["host"]
            port = config["port"]
            api_key = config["api_key"]
            endpoint = config["endpoint"]
            items_list = config["items"]

            logger.info(f"Connecting to daemon at {endpoint} via WebSocket...")

            daemon_config = DaemonConfig(ip=host, port=port, api_key=api_key)

            try:
                connection = connection_manager.get_or_create_connection(daemon_config)
                
                connection.on("connection_update", handle_connection_update)

                if connection.is_connected():
                    logger.info(f"Successfully connected to daemon at {endpoint} via WebSocket")

                    with Session(engine) as update_session:
                        for item in items_list:
                            update_item = update_session.get(Item, item.id)
                            if update_item:
                                update_item.status = ItemStatus.stopped
                                update_item.socket_connected = True
                                update_item.socket_last_connected = datetime.now()
                        update_session.commit()
                else:
                    logger.error(f"Failed to connect to daemon at {endpoint}")

                    with Session(engine) as update_session:
                        for item in items_list:
                            update_item = update_session.get(Item, item.id)
                            if update_item:
                                update_item.status = ItemStatus.stopped
                                update_item.socket_connected = False
                        update_session.commit()
            except Exception as e:
                logger.error(f"Error connecting to daemon at {endpoint}: {str(e)}")

                with Session(engine) as update_session:
                    for item in items_list:
                        update_item = update_session.get(Item, item.id)
                        if update_item:
                            update_item.status = ItemStatus.stopped
                            update_item.socket_connected = False
                    update_session.commit()

    logger.info("Daemon initialization completed")


def start_daemon_initialization():
    initialize_daemon_connections()


if __name__ == "__main__":
    start_daemon_initialization()
