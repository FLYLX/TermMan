import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Item, ItemCreate, ItemPublic, ItemsPublic, ItemUpdate, Message
from app.services import socket_manager, connection_manager

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/", response_model=Dict[str, Any])
def read_items(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve items.
    """

    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Item)
        count = session.exec(count_statement).one()
        statement = (
            select(Item).order_by(col(Item.created_at).desc()).offset(skip).limit(limit)
        )
        items = session.exec(statement).all()
        
        # 获取所有连接表信息
        connection_tables = socket_manager.get_connection_tables()
        item_user_conn_map = connection_tables.get('item_user_conn_map', {})
        
        # 为每个item添加已连接的用户信息
        items_with_users = []
        for item in items:
            item_data = ItemPublic.model_validate(item).model_dump()
            
            # 添加已连接的用户信息
            if str(item.id) in item_user_conn_map:
                connected_users = item_user_conn_map[str(item.id)]
                item_data['connected_users'] = connected_users
            else:
                item_data['connected_users'] = {}
            
            items_with_users.append(item_data)
        
        return {
            "data": items_with_users,
            "count": count
        }
    else:
        count_statement = (
            select(func.count())
            .select_from(Item)
            .where(Item.owner_id == current_user.id)
        )
        count = session.exec(count_statement).one()
        statement = (
            select(Item)
            .where(Item.owner_id == current_user.id)
            .order_by(col(Item.created_at).desc())
            .offset(skip).limit(limit)
        )
        items = session.exec(statement).all()
        
        # 获取所有连接表信息
        connection_tables = socket_manager.get_connection_tables()
        item_user_conn_map = connection_tables.get('item_user_conn_map', {})
        
        # 为每个item添加已连接的用户信息
        items_with_users = []
        for item in items:
            item_data = ItemPublic.model_validate(item).model_dump()
            
            # 添加已连接的用户信息
            if str(item.id) in item_user_conn_map:
                connected_users = item_user_conn_map[str(item.id)]
                item_data['connected_users'] = connected_users
            else:
                item_data['connected_users'] = {}
            
            items_with_users.append(item_data)
        
        return {
            "data": items_with_users,
            "count": count
        }


@router.get("/{id}", response_model=Dict[str, Any])
def read_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get item by ID.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # 创建基本响应
    item_data = ItemPublic.model_validate(item).model_dump()
    
    # 获取token信息
    token_info = socket_manager.get_token(item.id)
    if token_info:
        item_data["terminal_token"] = token_info.token
    
    # 获取daemon信息
    daemon_config = None
    for connection in connection_manager.connections.values():
        if connection.config.api_key == item.api_key:
            daemon_config = connection.config
            break
    
    if daemon_config:
        item_data["daemon_url"] = daemon_config.base_url
        item_data["daemon_ip"] = daemon_config.ip
        item_data["daemon_port"] = daemon_config.port
    
    return item_data


@router.post("/", response_model=ItemPublic)
def create_item(
    *, session: SessionDep, current_user: CurrentUser, item_in: ItemCreate
) -> Any:
    """
    Create new item.
    """
    item = Item.model_validate(item_in, update={"owner_id": current_user.id})
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.put("/{id}", response_model=ItemPublic)
def update_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_in: ItemUpdate,
) -> Any:
    """
    Update an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    update_dict = item_in.model_dump(exclude_unset=True)
    item.sqlmodel_update(update_dict)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.post("/{id}/disconnect-user")
def disconnect_user_from_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID, user_uuid: str
) -> Any:
    """
    Disconnect a specific user from a specific item.
    Only available to superusers.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # 验证item是否存在
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # 断开用户连接
    success = socket_manager.disconnect_user_from_item(str(id), user_uuid)
    
    if success:
        return {
            "success": True,
            "message": f"Successfully disconnected user {user_uuid} from item {id}"
        }
    else:
        return {
            "success": False,
            "message": f"Failed to disconnect user {user_uuid} from item {id}"
        }


@router.post("/{id}/stop")
def stop_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Stop an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # 实现停止逻辑
    import logging
    from app.models import ItemStatus
    from app.services import connection_manager
    from app.services.connection_pool.connection_models import DaemonConfig
    
    logger = logging.getLogger(__name__)
    
    # 检查item当前状态，如果已经停止或正在停止中，直接返回
    if item.status in [ItemStatus.stopped, ItemStatus.stopping]:
        return Message(message=f"Item {item.title} is already {item.status.value}")
    
    # 更新item状态为stopping
    item.status = ItemStatus.stopping
    session.commit()
    
    try:
        # 创建daemon配置
        daemon_id = f"daemon-{item.socket_host}-{item.socket_port}-{item.api_key[:8]}"
        daemon_config = DaemonConfig(
            daemon_id=daemon_id,
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )
        
        # 获取连接
        connection = connection_manager.get_connection(daemon_id)
        
        if connection and connection.is_connected():
            logger.info(f"Stopping item {item.id} on daemon {daemon_id}")
            
            # 使用HTTP方式停止终端
            result = connection.terminal_stop_http(str(item.id))
            
            if result.get("success"):
                # 更新item状态为stopped
                item.status = ItemStatus.stopped
                item.socket_connected = False
                session.commit()
                return Message(message="Item stopped successfully")
            else:
                # 更新item状态为error
                item.status = ItemStatus.error
                session.commit()
                raise HTTPException(status_code=500, detail=f"Failed to stop item: {result.get('error')}")
        else:
            # daemon连接失败，返回错误信息
            item.status = ItemStatus.error
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to connect to daemon")
    except Exception as e:
        # 出现异常，返回错误信息
        item.status = ItemStatus.error
        session.commit()
        logger.error(f"Error stopping item {item.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to stop item: {str(e)}")


@router.post("/{id}/restart")
def restart_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Restart an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # 实现重启逻辑
    import logging
    from datetime import datetime
    from app.models import ItemStatus
    from app.services import connection_manager
    from app.services.connection_pool.connection_models import DaemonConfig
    from app.services.socket_pool import socket_manager
    
    logger = logging.getLogger(__name__)
    
    # 先停止item
    item.status = ItemStatus.stopping
    session.commit()
    
    try:
        # 创建daemon配置
        daemon_id = f"daemon-{item.socket_host}-{item.socket_port}-{item.api_key[:8]}"
        daemon_config = DaemonConfig(
            daemon_id=daemon_id,
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )
        
        # 获取或创建连接
        connection = connection_manager.get_or_create_connection(daemon_config)
        
        if connection.is_connected():
            # 停止终端
            logger.info(f"Stopping item {item.id} on daemon {daemon_id} for restart")
            stop_result = connection.terminal_stop_http(str(item.id))
            
            # 移除旧的socket连接和token
            socket_manager.remove_all_sockets_by_item(str(item.id))
            
            # 更新状态为starting
            item.status = ItemStatus.starting
            session.commit()
            
            # 启动终端
            logger.info(f"Starting item {item.id} on daemon {daemon_id} for restart")
            start_result = connection.terminal_start_http(
                user_uuid=str(current_user.id),
                token="",  # 重启时不需要token
                working_directory=item.working_directory,
                command=item.command
            )
            
            if start_result.get("success"):
                # 获取daemon返回的token
                token = start_result.get("token")
                if token:
                    # 保存token信息
                    socket_manager.add_token(str(item.id), token)
                    
                    # 以backend的名义连接到item
                    daemon_url = f"http://{item.socket_host}:{item.socket_port}"
                    socket_manager.create_socket(
                        item_uuid=str(item.id),
                        token=token,
                        daemon_url=daemon_url,
                        user_uuid="backend",
                        api_key=item.api_key
                    )
                
                # 更新item状态为running
                item.status = ItemStatus.running
                session.commit()
                return Message(message="Item restarted successfully")
            else:
                # 更新item状态为error
                item.status = ItemStatus.error
                session.commit()
                raise HTTPException(status_code=500, detail=f"Failed to restart item: {start_result.get('error')}")
        else:
            # 更新item状态为error
            item.status = ItemStatus.error
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to connect to daemon")
    except Exception as e:
        # 更新item状态为error
        item.status = ItemStatus.error
        session.commit()
        logger.error(f"Error restarting item {item.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to restart item: {str(e)}")


@router.post("/{id}/start")
def start_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Start an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # 实现启动逻辑
    import logging
    from datetime import datetime
    from app.models import ItemStatus
    
    logger = logging.getLogger(__name__)
    
    # 检查item当前状态，如果已经在运行或正在启动中，直接返回
    if item.status in [ItemStatus.running, ItemStatus.starting]:
        return Message(message=f"Item {item.title} is already {item.status.value}")
    
    # 更新item状态为starting
    item.status = ItemStatus.starting
    item.socket_connected = True
    item.socket_last_connected = datetime.now()
    session.commit()
    
    try:
        # 查找对应的daemon连接
        from app.services import connection_manager
        from app.services.connection_pool.connection_models import DaemonConfig
        
        # 创建daemon配置
        daemon_id = f"daemon-{item.socket_host}-{item.socket_port}-{item.api_key[:8]}"
        daemon_config = DaemonConfig(
            daemon_id=daemon_id,
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )
        
        # 获取或创建连接
        connection = connection_manager.get_or_create_connection(daemon_config)
        
        if connection.is_connected():
            logger.info(f"Starting item {item.id} on daemon {daemon_id}")
            
            # 使用HTTP方式启动终端
            result = connection.terminal_start_http(
                user_uuid=str(current_user.id),
                token="",  # 初始启动时不需要token
                item_uuid=str(item.id),  # 传递item UUID给daemon
                working_directory=item.working_directory,
                command=item.command
            )
            
            if result.get("success"):
                # 获取daemon返回的token
                token = result.get("token")
                if token:
                    # 保存token信息
                    socket_manager.add_token(str(item.id), token)
                    
                    # 以backend的名义连接到item
                    daemon_url = f"http://{item.socket_host}:{item.socket_port}"
                    socket_manager.create_socket(
                        item_uuid=str(item.id),
                        token=token,
                        daemon_url=daemon_url,
                        user_uuid="backend",
                        api_key=item.api_key
                    )
                
                # 更新item状态为running
                item.status = ItemStatus.running
                session.commit()
                return Message(message="Item started successfully")
            else:
                # 更新item状态为error
                item.status = ItemStatus.error
                session.commit()
                raise HTTPException(status_code=500, detail=f"Failed to start item: {result.get('error')}")
        else:
            # 更新item状态为error
            item.status = ItemStatus.error
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to connect to daemon")
    except Exception as e:
        # 更新item状态为error
        item.status = ItemStatus.error
        session.commit()
        logger.error(f"Error starting item {item.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start item: {str(e)}")


@router.post("/{id}/connect")
def connect_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Connect to an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # 实现连接逻辑
    import logging
    from datetime import datetime
    from app.models import ItemStatus
    from app.services import connection_manager
    from app.services.connection_pool.connection_models import DaemonConfig
    
    logger = logging.getLogger(__name__)
    
    try:
        # 创建daemon配置
        daemon_id = f"daemon-{item.socket_host}-{item.socket_port}-{item.api_key[:8]}"
        daemon_config = DaemonConfig(
            daemon_id=daemon_id,
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )
        
        # 获取或创建连接
        connection = connection_manager.get_or_create_connection(daemon_config)
        
        if connection.is_connected():
            logger.info(f"Connected to daemon {daemon_id} for item {item.id}")
            
            # 更新item状态
            item.socket_connected = True
            item.socket_last_connected = datetime.now()
            
            # 如果item状态是stopped，保持stopped状态
            # 如果item状态是error，可能需要考虑是否要改为stopped
            
            session.commit()
            return Message(message="Item connected successfully")
        else:
            # 更新item状态
            item.socket_connected = False
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to connect to daemon")
    except Exception as e:
        # 更新item状态
        item.socket_connected = False
        session.commit()
        logger.error(f"Error connecting to daemon for item {item.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to connect to daemon: {str(e)}")


@router.delete("/{id}")
def delete_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    session.delete(item)
    session.commit()
    return Message(message="Item deleted successfully")
