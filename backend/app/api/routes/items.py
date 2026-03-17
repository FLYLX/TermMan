import logging
import uuid
from typing import Any
import asyncio

from fastapi import APIRouter, HTTPException
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Item, ItemCreate, ItemPublic, ItemUpdate, Message
from app.services import DaemonConfig, connection_manager, socket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])


def _get_daemon_status(item: Item) -> dict:
    """
    获取item对应daemon的连接状态
    
    Args:
        item: Item对象
        
    Returns:
        dict: 包含daemon_id, daemon_online, daemon_status
    """
    if not item.socket_host or not item.socket_port or not item.api_key:
        return {
            "daemon_id": None,
            "daemon_online": False,
            "daemon_status": "not_configured"
        }
    
    daemon_id = f"{item.socket_host}:{item.socket_port}:{item.api_key}"
    
    daemon_connection = connection_manager.get_connection(daemon_id)
    
    if daemon_connection and daemon_connection.is_connected():
        return {
            "daemon_id": daemon_id,
            "daemon_online": True,
            "daemon_status": "connected"
        }
    else:
        return {
            "daemon_id": daemon_id,
            "daemon_online": False,
            "daemon_status": "disconnected"
        }


@router.get("/", response_model=dict[str, Any])
def read_items(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Item)
        count = session.exec(count_statement).one()
        statement = (
            select(Item).order_by(col(Item.created_at).desc()).offset(skip).limit(limit)
        )
        items = session.exec(statement).all()

        connection_tables = socket_manager.get_connection_tables()
        item_connections = connection_tables.get('item_connections', {})

        items_with_users = []
        for item in items:
            item_data = ItemPublic.model_validate(item).model_dump()
            item_data["daemon_url"] = f"http://{item.socket_host}:{item.socket_port}"
            
            daemon_status = _get_daemon_status(item)
            item_data["daemon_id"] = daemon_status["daemon_id"]
            item_data["daemon_online"] = daemon_status["daemon_online"]
            item_data["daemon_status"] = daemon_status["daemon_status"]

            if str(item.id) in item_connections:
                item_data['connected_users'] = item_connections[str(item.id)]
            else:
                item_data['connected_users'] = {}

            items_with_users.append(item_data)

        return {"data": items_with_users, "count": count}
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

        connection_tables = socket_manager.get_connection_tables()
        item_connections = connection_tables.get('item_connections', {})

        items_with_users = []
        for item in items:
            item_data = ItemPublic.model_validate(item).model_dump()
            item_data["daemon_url"] = f"http://{item.socket_host}:{item.socket_port}"
            
            daemon_status = _get_daemon_status(item)
            item_data["daemon_id"] = daemon_status["daemon_id"]
            item_data["daemon_online"] = daemon_status["daemon_online"]
            item_data["daemon_status"] = daemon_status["daemon_status"]

            if str(item.id) in item_connections:
                item_data['connected_users'] = item_connections[str(item.id)]
            else:
                item_data['connected_users'] = {}

            items_with_users.append(item_data)

        return {"data": items_with_users, "count": count}


@router.get("/{id}", response_model=dict[str, Any])
def read_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    item_data = ItemPublic.model_validate(item).model_dump()
    item_data["daemon_url"] = f"http://{item.socket_host}:{item.socket_port}"
    
    daemon_status = _get_daemon_status(item)
    item_data["daemon_id"] = daemon_status["daemon_id"]
    item_data["daemon_online"] = daemon_status["daemon_online"]
    item_data["daemon_status"] = daemon_status["daemon_status"]

    connection_tables = socket_manager.get_connection_tables()
    item_connections = connection_tables.get('item_connections', {})
    item_tokens = connection_tables.get('item_tokens', {})

    if str(item.id) in item_connections:
        item_data['connected_users'] = item_connections[str(item.id)]
    else:
        item_data['connected_users'] = {}
    
    if str(item.id) in item_tokens:
        item_data['token'] = item_tokens[str(item.id)]

    return item_data


@router.post("/daemon/reconnect")
def reconnect_daemon(
    session: SessionDep, current_user: CurrentUser, daemon_id: str
) -> Any:
    """
    尝试重新连接daemon
    
    Args:
        daemon_id: daemon的唯一标识 (host:port:api_key)
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    parts = daemon_id.split(":")
    if len(parts) < 3:
        raise HTTPException(status_code=400, detail="Invalid daemon_id format")
    
    host = parts[0]
    port = int(parts[1])
    api_key = ":".join(parts[2:])
    
    config = DaemonConfig(ip=host, port=port, api_key=api_key)
    result = connection_manager.reconnect_connection(config)
    
    return result


@router.post("/", response_model=ItemPublic)
def create_item(
    *, session: SessionDep, current_user: CurrentUser, item_in: ItemCreate
) -> Any:
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
async def disconnect_user_from_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID, user_uuid: str
) -> Any:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if user_uuid == "backend":
        return {"success": False, "message": "Cannot disconnect backend connection"}

    logger.info(f"Disconnecting user {user_uuid} from item {id}...")

    try:
        daemon_config = DaemonConfig(
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )

        connection = connection_manager.get_or_create_connection(daemon_config)

        if connection.is_connected():
            logger.info(f"Sending disconnect request for user {user_uuid} from item {id} to daemon")

            disconnect_result = await connection.disconnect_connection(str(id), user_uuid=user_uuid)

            if disconnect_result.get("success"):
                connections = disconnect_result.get("connections", {})
                socket_manager.update_connections_from_daemon(str(id), connections)
                logger.info(f"Updated backend connection table for item {id} after disconnect")

                return {
                    "success": True,
                    "message": disconnect_result.get("message", f"Successfully disconnected user {user_uuid}")
                }
            else:
                return {
                    "success": False,
                    "message": disconnect_result.get("error", f"Failed to disconnect user {user_uuid}")
                }
        else:
            return {"success": False, "message": "Failed to connect to daemon"}
    except Exception as e:
        logger.error(f"Error disconnecting user {user_uuid} from item {id}: {str(e)}")
        return {"success": False, "message": f"Failed to disconnect user {user_uuid}: {str(e)}"}


@router.post("/{id}/stop")
async def stop_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Stop an item via WebSocket.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    from app.models import ItemStatus

    logger.info(f"Stopping item {item.id}...")

    try:
        daemon_config = DaemonConfig(
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )

        connection = connection_manager.get_or_create_connection(daemon_config)

        if connection.is_connected():
            logger.info(f"Sending stop request for item {item.id} to daemon via WebSocket")

            result = await connection.terminal_stop(str(item.id))

            if result.get("success"):
                socket_manager.remove_all_tokens_by_item(str(item.id))
                socket_manager.remove_all_sockets_by_item(str(item.id))

                item.status = ItemStatus.stopped
                item.socket_connected = False
                session.commit()
                logger.info(f"Item {item.id} stopped successfully")
                socket_manager._print_connection_tables(f"Item {item.id} stopped")

                return Message(message=result.get("message", "Item stopped successfully"))
            else:
                item.status = ItemStatus.error
                item.socket_connected = False
                session.commit()
                raise HTTPException(status_code=500, detail=f"Failed to stop item: {result.get('error')}")
        else:
            item.status = ItemStatus.error
            item.socket_connected = False
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to connect to daemon")
    except HTTPException:
        raise
    except Exception as e:
        item.status = ItemStatus.error
        item.socket_connected = False
        session.commit()
        logger.error(f"Error stopping item {item.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to stop item: {str(e)}")


@router.post("/{id}/restart")
async def restart_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Restart an item via WebSocket.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    from app.models import ItemStatus

    item.status = ItemStatus.stopping
    session.commit()

    try:
        daemon_config = DaemonConfig(
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )

        connection = connection_manager.get_or_create_connection(daemon_config)

        if connection.is_connected():
            logger.info(f"Restarting item {item.id} via WebSocket")

            result = await connection.terminal_restart(
                item_uuid=str(item.id),
                user_uuid=str(current_user.id),
                working_directory=item.working_directory,
                command=item.command
            )

            if result.get("success"):
                token = result.get("token")
                
                if token:
                    daemon_id = f"{item.socket_host}:{item.socket_port}:{item.api_key}"
                    socket_manager.add_token(daemon_id, str(item.id), token)

                item.status = ItemStatus.running
                item.socket_connected = True
                session.commit()
                return Message(message=result.get("message", "Item restarted successfully"))
            else:
                item.status = ItemStatus.error
                session.commit()
                raise HTTPException(status_code=500, detail=f"Failed to restart item: {result.get('error')}")
        else:
            item.status = ItemStatus.error
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to connect to daemon")
    except HTTPException:
        raise
    except Exception as e:
        item.status = ItemStatus.error
        session.commit()
        logger.error(f"Error restarting item {item.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to restart item: {str(e)}")


@router.post("/{id}/start")
async def start_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Start an item via WebSocket.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    from datetime import datetime
    from app.models import ItemStatus

    logger.info(f"Starting item {item.id}...")

    try:
        daemon_config = DaemonConfig(
            ip=item.socket_host,
            port=item.socket_port,
            api_key=item.api_key
        )

        connection = connection_manager.get_or_create_connection(daemon_config)

        if connection.is_connected():
            logger.info(f"Sending start request for item {item.id} to daemon via WebSocket")

            result = await connection.terminal_start(
                user_uuid=str(current_user.id),
                item_uuid=str(item.id),
                working_directory=item.working_directory,
                command=item.command
            )

            if result.get("success"):
                token = result.get("token")
                
                if token:
                    daemon_id = f"{item.socket_host}:{item.socket_port}:{item.api_key}"
                    socket_manager.add_token(daemon_id, str(item.id), token)

                item.status = ItemStatus.running
                item.socket_connected = True
                item.socket_last_connected = datetime.now()
                session.commit()
                logger.info(f"Item {item.id} started successfully")
                socket_manager._print_connection_tables(f"Item {item.id} started")

                return Message(message=result.get("message", "Item started successfully"))
            else:
                item.status = ItemStatus.error
                item.socket_connected = False
                session.commit()
                raise HTTPException(status_code=500, detail=f"Failed to start item: {result.get('error')}")
        else:
            item.status = ItemStatus.error
            item.socket_connected = False
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to connect to daemon")
    except HTTPException:
        raise
    except Exception as e:
        item.status = ItemStatus.error
        item.socket_connected = False
        session.commit()
        logger.error(f"Error starting item {item.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start item: {str(e)}")


@router.delete("/{id}")
def delete_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    socket_manager.remove_all_sockets_by_item(str(item.id))
    socket_manager.remove_all_tokens_by_item(str(item.id))

    session.delete(item)
    session.commit()
    return Message(message="Item deleted successfully")
