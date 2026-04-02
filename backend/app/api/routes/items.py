import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Item,
    ItemCreate,
    ItemPublic,
    ItemStatus,
    ItemUpdate,
    Message,
    User,
)
from app.services import (
    DaemonConfig,
    backend_conn_pool,
    connection_manager,
    log_manager,
    socket_pool_facade,
    sync_daemon_connection_state,
)
from app.services.filters import (
    InputFilter,
    InputFilterConfig,
    OutputFilter,
    OutputFilterConfig,
)
from app.services.terminal_service import TerminalService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])


def _get_daemon_status(item: Item) -> dict:
    """获取item对应daemon的连接状态"""
    if not item.socket_host or not item.socket_port or not item.api_key:
        return {"daemon_id": None, "daemon_online": False, "daemon_status": "not_configured"}
    
    daemon_id = f"{item.socket_host}:{item.socket_port}:{item.api_key}"
    daemon_state = backend_conn_pool.get_daemon_main_conn_state(item.api_key)
    
    if daemon_state and daemon_state.is_connected():
        return {"daemon_id": daemon_id, "daemon_online": True, "daemon_status": "connected"}
    return {"daemon_id": daemon_id, "daemon_online": False, "daemon_status": "disconnected"}


def _get_item_data(item: Item, session: SessionDep = None) -> dict:
    """获取item的完整数据（包含daemon状态和连接信息）"""
    item_data = ItemPublic.model_validate(item).model_dump()
    item_data["daemon_url"] = f"http://{item.socket_host}:{item.socket_port}"
    
    daemon_status = _get_daemon_status(item)
    item_data["daemon_id"] = daemon_status["daemon_id"]
    item_data["daemon_online"] = daemon_status["daemon_online"]
    item_data["daemon_status"] = daemon_status["daemon_status"]
    
    daemon_id, token = socket_pool_facade.get_item_token(str(item.id))
    if token:
        item_data['token'] = token
    
    subscribers = _get_item_subscribers_internal(item)
    
    if session and subscribers.get("subscribers"):
        user_ids = set()
        for sub in subscribers["subscribers"]:
            if sub.get("user_uuid"):
                try:
                    user_ids.add(uuid.UUID(sub["user_uuid"]))
                except (ValueError, TypeError):
                    pass
        
        if user_ids:
            users = session.exec(select(User).where(User.id.in_(user_ids))).all()
            user_map = {str(user.id): user.full_name or user.email for user in users}
            
            for sub in subscribers["subscribers"]:
                user_uuid = sub.get("user_uuid", "")
                sub["user_name"] = user_map.get(user_uuid, user_uuid[:8] + "...")
    
    item_data["subscribers"] = subscribers.get("subscribers", [])
    item_data["browser_count"] = subscribers.get("browser_count", 0)
    item_data["backend_connected"] = subscribers.get("backend_connected", False)
    
    return item_data


def _get_item_subscribers_internal(item: Item) -> dict:
    """获取item的订阅者信息（内部方法）"""
    daemon_status = _get_daemon_status(item)
    if not daemon_status["daemon_online"]:
        return {
            "subscribers": [],
            "browser_count": 0,
            "backend_connected": False
        }
    
    connection = connection_manager.get_connection(
        f"{item.socket_host}:{item.socket_port}:{item.api_key}"
    )
    
    if not connection or not connection.is_connected():
        return {
            "subscribers": [],
            "browser_count": 0,
            "backend_connected": False
        }
    
    result = connection.get_item_subscribers_http(str(item.id))
    return result


def _check_item_permission(item: Item, current_user: CurrentUser):
    """检查用户对item的权限"""
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")


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

    items_with_data = [_get_item_data(item, session) for item in items]
    return {"data": items_with_data, "count": count}


@router.get("/{id}", response_model=dict[str, Any])
def read_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    return _get_item_data(item)


@router.post("/daemon/reconnect")
def reconnect_daemon(
    session: SessionDep, current_user: CurrentUser, daemon_id: str
) -> Any:
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
    if result.get("success"):
        sync_daemon_connection_state(config)
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
    _check_item_permission(item, current_user)
    
    update_dict = item_in.model_dump(exclude_unset=True)
    item.sqlmodel_update(update_dict)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.post("/{id}/start")
async def start_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    daemon_config = DaemonConfig(
        ip=item.socket_host,
        port=item.socket_port,
        api_key=item.api_key
    )
    
    terminal_service = TerminalService(connection_manager, socket_pool_facade)
    result = terminal_service.start_terminal(
        item_uuid=str(item.id),
        user_uuid=str(current_user.id),
        daemon_config=daemon_config
    )
    
    if result["success"]:
        item.status = ItemStatus.running
        item.socket_connected = True
        session.commit()
        return Message(message=result.get("message", "Item started successfully"))
    else:
        item.status = ItemStatus.error
        item.socket_connected = False
        session.commit()
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to start item"))


@router.post("/{id}/stop")
async def stop_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    terminal_service = TerminalService(connection_manager, socket_pool_facade)
    result = terminal_service.stop_terminal(
        daemon_id=f"{item.socket_host}:{item.socket_port}:{item.api_key}",
        item_uuid=str(item.id)
    )
    
    if result["success"]:
        item.status = ItemStatus.stopped
        item.socket_connected = False
        session.commit()
        return Message(message=result.get("message", "Item stopped successfully"))
    else:
        item.status = ItemStatus.error
        session.commit()
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to stop item"))


@router.post("/{id}/restart")
async def restart_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    item.status = ItemStatus.stopping
    session.commit()
    
    daemon_config = DaemonConfig(
        ip=item.socket_host,
        port=item.socket_port,
        api_key=item.api_key
    )
    
    terminal_service = TerminalService(connection_manager, socket_pool_facade)
    
    stop_result = terminal_service.stop_terminal(
        daemon_id=f"{item.socket_host}:{item.socket_port}:{item.api_key}",
        item_uuid=str(item.id)
    )
    
    if not stop_result["success"]:
        logger.warning(f"Stop failed during restart: {stop_result.get('error')}")
    
    start_result = terminal_service.start_terminal(
        item_uuid=str(item.id),
        user_uuid=str(current_user.id),
        daemon_config=daemon_config
    )
    
    if start_result["success"]:
        item.status = ItemStatus.running
        item.socket_connected = True
        session.commit()
        return Message(message=start_result.get("message", "Item restarted successfully"))
    else:
        item.status = ItemStatus.error
        session.commit()
        raise HTTPException(status_code=500, detail=start_result.get("error", "Failed to restart item"))


@router.delete("/{id}")
def delete_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    socket_pool_facade.cleanup_item_runtime(str(item.id))
    backend_conn_pool.remove_room_listen_conn(str(item.id))
    
    session.delete(item)
    session.commit()
    return Message(message="Item deleted successfully")


@router.get("/{id}/terminal-token")
def get_terminal_token(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> dict[str, Any]:
    from app.services.auth_service import auth_service
    
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    daemon_id, daemon_token = socket_pool_facade.get_item_token(str(item.id))
    
    if not daemon_token:
        raise HTTPException(status_code=400, detail="Item not running or token not available")
    
    daemon_status = _get_daemon_status(item)
    if not daemon_status["daemon_online"]:
        raise HTTPException(status_code=400, detail="Daemon is not connected")
    
    temp_token_info = auth_service.generate_terminal_temp_token(
        item_uuid=str(id),
        user_id=str(current_user.id),
        expire_minutes=5
    )
    
    logger.info(f"Generated terminal temp token for user={current_user.id}, item={id}")
    
    return {
        "success": True,
        "temp_token": temp_token_info["token"],
        "item_uuid": str(id),
        "user_uuid": str(current_user.id),
        "ws_url": f"ws://{item.socket_host}:{item.socket_port}",
        "daemon_id": daemon_id,
        "expire_seconds": temp_token_info["expires_in"]
    }


@router.post("/{id}/verify-terminal-token")
def verify_terminal_token(
    session: SessionDep,
    id: uuid.UUID,
    temp_token: str = Body(...),
    item_uuid: str = Body(...)
) -> dict[str, Any]:
    from app.services.auth_service import auth_service
    
    if str(id) != item_uuid:
        return {"success": False, "error": "Item UUID mismatch"}
    
    result = auth_service.validate_terminal_temp_token(
        token=temp_token,
        item_uuid=item_uuid,
        mark_used=True
    )
    
    if result["success"]:
        logger.info(f"Terminal temp token verified for item={id}, user={result['user_id']}")
    else:
        logger.warning(f"Terminal temp token verification failed: {result['error']}")
    
    return result


@router.get("/{id}/subscribers")
def get_item_subscribers(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> dict[str, Any]:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    daemon_status = _get_daemon_status(item)
    if not daemon_status["daemon_online"]:
        return {
            "success": True,
            "item_uuid": str(id),
            "subscribers": [],
            "browser_count": 0,
            "backend_connected": False,
            "daemon_online": False
        }
    
    connection = connection_manager.get_connection(
        f"{item.socket_host}:{item.socket_port}:{item.api_key}"
    )
    
    if not connection or not connection.is_connected():
        return {
            "success": True,
            "item_uuid": str(id),
            "subscribers": [],
            "browser_count": 0,
            "backend_connected": False,
            "daemon_online": True,
            "error": "Backend not connected to daemon"
        }
    
    result = connection.get_item_subscribers_http(str(id))
    
    result["daemon_online"] = True
    return result


@router.post("/{id}/disconnect-subscriber")
def disconnect_item_subscriber(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    user_uuid: str = Body(default=None),
    ip_address: str = Body(default=None)
) -> dict[str, Any]:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    if not user_uuid and not ip_address:
        raise HTTPException(status_code=400, detail="Must provide user_uuid or ip_address")
    
    daemon_status = _get_daemon_status(item)
    if not daemon_status["daemon_online"]:
        raise HTTPException(status_code=400, detail="Daemon is not connected")
    
    connection = connection_manager.get_connection(
        f"{item.socket_host}:{item.socket_port}:{item.api_key}"
    )
    
    if not connection or not connection.is_connected():
        raise HTTPException(status_code=400, detail="Backend not connected to daemon")
    
    result = connection.disconnect_connection_http(
        item_uuid=str(id),
        user_uuid=user_uuid,
        ip_address=ip_address
    )
    
    return result


@router.get("/{id}/output")
def get_item_output(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    lines: int = 64
) -> dict[str, Any]:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    if lines < 1 or lines > 1000:
        raise HTTPException(status_code=400, detail="lines must be between 1 and 1000")
    
    output = log_manager.get_last_lines(str(id), lines)
    
    return {
        "success": True,
        "item_uuid": str(id),
        "lines": lines,
        "output": output
    }


@router.post("/{id}/test-input-filter")
def test_input_filter(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    test_text: str = Body(..., embed=True),
) -> dict[str, Any]:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    config = InputFilterConfig.from_item(item)
    input_filter = InputFilter(config)
    
    stream_data = {"stdout": test_text, "stderr": ""}
    result = input_filter.filter(stream_data)
    
    if result is None:
        return {
            "success": True,
            "result": "",
            "event_type": "blocked",
            "matched_filters": [],
            "matches": [],
        }
    
    return {
        "success": True,
        "result": result.raw_content,
        "event_type": result.event_type.value,
        "matched_filters": result.matched_filters,
        "matches": result.matches[:20],
    }


@router.post("/{id}/test-output-filter")
def test_output_filter(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    command: str = Body(..., embed=True),
) -> dict[str, Any]:
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    _check_item_permission(item, current_user)
    
    config = OutputFilterConfig.from_item(item)
    output_filter = OutputFilter(config)
    
    result = output_filter.filter(command)
    
    return {
        "success": True,
        "original_command": command,
        "result": "" if result.is_blocked else result.command,
        "action": result.action.value,
        "reason": result.reason,
        "is_allowed": result.is_allowed,
        "is_blocked": result.is_blocked,
        "matched_filters": result.matched_filters,
        "matches": result.matches[:20],
    }
