"""
Daemon连接初始化模块
负责在应用启动时初始化所有daemon连接
"""

from sqlmodel import Session
from app.core.db import engine
from app.models import Item, ItemStatus
from app.services.connection_pool import ConnectionManager, DaemonConfig
from app.services.socket_pool import SocketManager
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 全局连接管理器实例
connection_manager = ConnectionManager()

# 全局Socket管理器实例
socket_manager = SocketManager()


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
                        "items": [item]  # 存储所有属于这个daemon的items
                    }
                else:
                    # 将当前item添加到已存在的daemon配置中
                    unique_configs[unique_key]["items"].append(item)
                    logger.debug(f"Added item {item.id} to existing daemon config {unique_key}")
        
        logger.info(f"Found {len(unique_configs)} unique api_key:ip:port combinations")
        logger.info(f"Processed {len(items)} items in total")
        
        # 为每个唯一的api_key:ip:port组合创建连接
        for unique_key, config in unique_configs.items():
            host = config["host"]
            port = config["port"]
            api_key = config["api_key"]
            endpoint = config["endpoint"]
            items = config["items"]
            
            logger.info(f"Connecting to daemon at {endpoint} with API key: {api_key[:8]} (for {len(items)} items)...")
            
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
                    logger.info(f"Successfully connected to daemon at {endpoint}")
                    
                    # 首先，将所有属于该daemon的items初始状态设置为stopped
                    # 因为即使daemon连接成功，如果没有运行的终端，item也应该是stopped状态
                    with Session(engine) as update_session:
                        for item in items:
                            update_item = update_session.get(Item, item.id)
                            if update_item:
                                update_item.status = ItemStatus.stopped
                                update_item.socket_connected = True
                                update_item.socket_last_connected = datetime.now()
                                logger.info(f"Updated item {item.id} status to stopped and socket_connected to True")
                        update_session.commit()
                    
                    # 从daemon获取运行中的终端列表
                    logger.info(f"Fetching running terminals from daemon at {endpoint}...")
                    terminals_result = connection.get_terminals_http()
                    running_item_uuids = set()
                    
                    if terminals_result.get("success"):
                        terminals = terminals_result.get("data", [])
                        if terminals:
                            daemon_url = f"ws://{host}:{port}"
                            logger.info(f"Found {len(terminals)} terminals on daemon at {endpoint}")
                            
                            # 收集所有运行中的终端对应的item_uuid
                            for terminal in terminals:
                                terminal_item_uuid = terminal.get("item_uuid")
                                if terminal_item_uuid:
                                    running_item_uuids.add(terminal_item_uuid)
                                    
                                    # 从memory_store获取token
                                    token = socket_manager.get_token(terminal_item_uuid)
                                    if not token:
                                        # 如果没有token，生成一个新的
                                        import uuid
                                        token_value = str(uuid.uuid4())
                                        token = socket_manager.add_token(terminal_item_uuid, token_value)
                                        logger.info(f"Generated new token for terminal {terminal_item_uuid}")
                                    
                                    # 为backend创建一个特殊的系统用户连接
                                    backend_user_uuid = "backend-system-user"
                                    logger.info(f"Creating backend socket connection for terminal {terminal_item_uuid}...")
                                    
                                    # 创建socket连接
                                    socket = socket_manager.get_or_create_socket(
                                        terminal_item_uuid, 
                                        token.token,  # token是TokenInfo对象，需要获取token属性
                                        daemon_url, 
                                        backend_user_uuid, 
                                        api_key
                                    )
                                    
                                    if socket.is_connected():
                                        logger.info(f"Successfully created backend socket connection for terminal {terminal_item_uuid}")
                                    else:
                                        logger.error(f"Failed to create backend socket connection for terminal {terminal_item_uuid}")
                        else:
                            logger.info(f"No running terminals found on daemon at {endpoint}")
                    else:
                        logger.warning(f"Failed to get terminals from daemon at {endpoint}: {terminals_result.get('error', 'Unknown error')}")
                    
                    # 将有运行终端的items设置为running状态
                    if running_item_uuids:
                        with Session(engine) as update_session:
                            for item in items:
                                if str(item.id) in running_item_uuids:
                                    update_item = update_session.get(Item, item.id)
                                    if update_item:
                                        update_item.status = ItemStatus.running
                                        logger.info(f"Updated item {item.id} status to running (has active terminal)")
                            update_session.commit()
                    
                    # 从daemon获取socket连接表并导入
                    logger.info(f"Fetching socket connections from daemon at {endpoint}...")
                    socket_result = connection.get_socket_connections_http()
                    if socket_result.get("success"):
                        data = socket_result.get("data", {})
                        connections = data.get("item_user_conn_map", {})
                        if connections:
                            daemon_url = f"ws://{host}:{port}"
                            for conn_item_uuid, user_connections in connections.items():
                                success = socket_manager.import_socket_connections(
                                    conn_item_uuid, 
                                    user_connections, 
                                    daemon_url, 
                                    api_key
                                )
                                if success:
                                    logger.info(f"Imported {len(user_connections)} socket connections for item {conn_item_uuid} from daemon {endpoint}")
                                else:
                                    logger.error(f"Failed to import socket connections for item {conn_item_uuid} from daemon {endpoint}")
                        else:
                            logger.info(f"No socket connections found on daemon at {endpoint}")
                    else:
                        logger.warning(f"Failed to get socket connections from daemon at {endpoint}: {socket_result.get('error', 'Unknown error')}")
                else:
                    logger.error(f"Failed to connect to daemon at {endpoint}")
                    
                    # 更新该daemon的所有items的状态为停止
                    with Session(engine) as update_session:
                        for item in items:
                            update_item = update_session.get(Item, item.id)
                            if update_item:
                                update_item.status = ItemStatus.stopped
                                update_item.socket_connected = False
                                logger.info(f"Updated item {item.id} status to stopped and socket_connected to False")
                        update_session.commit()
            except Exception as e:
                logger.error(f"Error connecting to daemon at {endpoint}: {str(e)}")
                
                # 更新该daemon的所有items的状态为停止
                with Session(engine) as update_session:
                    for item in items:
                        update_item = update_session.get(Item, item.id)
                        if update_item:
                            update_item.status = ItemStatus.stopped
                            update_item.socket_connected = False
                            logger.info(f"Updated item {item.id} status to stopped and socket_connected to False due to error")
                    update_session.commit()
    
    logger.info("Startup event completed")


if __name__ == "__main__":
    initialize_daemon_connections()
