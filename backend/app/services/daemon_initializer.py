"""
Daemon连接初始化模块
负责在应用启动时初始化所有daemon连接
"""

from sqlmodel import Session
from app.core.db import engine
from app.models import Item
from app.services.connection_pool import ConnectionManager, DaemonConfig
import logging

logger = logging.getLogger(__name__)

# 全局连接管理器实例
connection_manager = ConnectionManager()


def initialize_daemon_connections():
    """
    初始化daemon连接的主要函数：
    1. 检索所有item
    2. 提取不重复的ip:port:api_key组合
    3. 为每个daemon创建连接
    4. 将连接添加到连接池
    """
    logger.info("Starting up application and initializing daemon connections...")
    
    # 获取数据库会话
    with Session(engine) as session:
        # 检索所有item
        items = session.query(Item).all()
        logger.info(f"Found {len(items)} items in database")
        
        # 提取api_key和ip:port都不重复的item组合
        unique_configs = {}
        processed_items = []
        
        for item in items:
            if item.socket_host and item.socket_port and item.api_key:
                # 创建由api_key和ip:port组成的唯一标识
                unique_key = f"{item.api_key}:{item.socket_host}:{item.socket_port}"
                
                if unique_key not in unique_configs:
                    # 第一次遇到这个api_key和ip:port组合，添加到配置中
                    unique_configs[unique_key] = {
                        "host": item.socket_host,
                        "port": item.socket_port,
                        "api_key": item.api_key,
                        "endpoint": f"{item.socket_host}:{item.socket_port}",
                        "item": item  # 存储对应的item
                    }
                    processed_items.append(item.id)
                else:
                    # 已经处理过这个组合，跳过
                    logger.debug(f"Skipping duplicate item {item.id} with same api_key and endpoint as item {unique_configs[unique_key]['item'].id}")
        
        logger.info(f"Found {len(unique_configs)} unique api_key:ip:port combinations")
        logger.info(f"Processed {len(processed_items)} items, skipped {len(items) - len(processed_items)} duplicates")
        
        # 为每个唯一的api_key:ip:port组合创建连接
        for unique_key, config in unique_configs.items():
            host = config["host"]
            port = config["port"]
            api_key = config["api_key"]
            endpoint = config["endpoint"]
            item = config["item"]
            
            logger.info(f"Connecting to daemon at {endpoint} with API key: {api_key[:8]} (for item {item.id}: {item.title})...")
            
            # 创建daemon配置，使用api_key的前8位作为daemon_id的一部分，确保唯一性
            daemon_id = f"daemon-{host}-{port}-{api_key[:8]}"
            daemon_config = DaemonConfig(
                daemon_id=daemon_id,
                ip=host,
                port=port,
                api_key=api_key
            )
            
            try:
                # 获取或创建连接
                connection = connection_manager.get_or_create_connection(daemon_config)
                
                if connection.is_connected():
                    logger.info(f"Successfully connected to daemon at {endpoint} for item {item.id}")
                else:
                    logger.error(f"Failed to connect to daemon at {endpoint} for item {item.id}")
            except Exception as e:
                logger.error(f"Error connecting to daemon at {endpoint} for item {item.id}: {str(e)}")
    
    logger.info("Startup event completed")


if __name__ == "__main__":
    initialize_daemon_connections()
