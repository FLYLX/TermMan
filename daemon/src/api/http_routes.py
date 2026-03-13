from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Dict, Any
from service.terminal_manager import terminal_manager
from core import memory_store, config
from utils.logger import logger

router = APIRouter()


def verify_api_key(request: Request):
    """
    验证API Key
    """
    api_key = request.headers.get("X-API-Key")
    expected_api_key = config.get("API_KEY")
    if not api_key or api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")


@router.post("/terminal/start")
async def start_terminal(data: Dict[str, Any], api_key: Any = Depends(verify_api_key)):
    """
    启动终端
    """
    user_uuid = data.get("user_uuid")
    token = data.get("token")

    if not user_uuid:
        raise HTTPException(status_code=400, detail="Missing user_uuid")

    # 创建终端
    item_uuid = terminal_manager.create_terminal(user_uuid, token)
    memory_store.set(f"terminal_token:{item_uuid}", token, ttl_minutes=1440)

    # 启动终端进程
    if not terminal_manager.start_terminal(item_uuid):
        raise HTTPException(status_code=500, detail="Failed to start terminal")

    logger.info(f"Terminal started via HTTP: {item_uuid}")
    return {
        "success": True,
        "item_uuid": item_uuid,
        "token": token
    }


@router.post("/terminal/stop")
async def stop_terminal(data: Dict[str, Any], api_key: Any = Depends(verify_api_key)):
    """
    停止终端
    """
    item_uuid = data.get("item_uuid")
    if not item_uuid:
        raise HTTPException(status_code=400, detail="Missing item_uuid")

    terminal = terminal_manager.get_terminal(item_uuid)
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal not found")

    if not terminal_manager.stop_terminal(item_uuid):
        raise HTTPException(status_code=500, detail="Failed to stop terminal")

    # 撤销token
    memory_store.delete(f"terminal_token:{item_uuid}")

    logger.info(f"Terminal stopped via HTTP: {item_uuid}")
    return {
        "success": True,
        "item_uuid": item_uuid
    }


@router.get("/terminal/status/{item_uuid}")
async def get_terminal_status(item_uuid: str, api_key: Any = Depends(verify_api_key)):
    """
    获取终端状态
    """
    terminal = terminal_manager.get_terminal(item_uuid)
    if not terminal:
        raise HTTPException(status_code=404, detail="Terminal not found")

    status = terminal.get_status()
    logger.info(f"Terminal status queried: {item_uuid}, status: {status['status']}")
    return {
        "success": True,
        "data": status
    }


@router.get("/terminal/list")
async def list_terminals(api_key: Any = Depends(verify_api_key)):
    """
    获取所有终端列表
    """
    terminals = terminal_manager.get_all_terminals()
    logger.info(f"Terminal list queried, count: {len(terminals)}")
    return {
        "success": True,
        "count": len(terminals),
        "data": terminals
    }


@router.get("/terminal/list/{user_uuid}")
async def list_user_terminals(user_uuid: str, api_key: Any = Depends(verify_api_key)):
    """
    获取用户的所有终端列表
    """
    terminals = terminal_manager.get_user_terminals(user_uuid)
    logger.info(f"User terminals queried: {user_uuid}, count: {len(terminals)}")
    return {
        "success": True,
        "count": len(terminals),
        "data": terminals
    }


@router.get("/status")
async def get_daemon_status():
    """
    获取Daemon状态
    """
    from ..core import config
    return {
        "success": True,
        "version": "0.1.0",
        "status": "running",
        "terminal_count": len(terminal_manager.get_all_terminals())
    }


@router.get("/connections")
async def get_connections(api_key: Any = Depends(verify_api_key)):
    """
    获取所有连接表
    """
    from core import get_socket_service
    socket_service = get_socket_service()
    if not socket_service:
        raise HTTPException(status_code=500, detail="Socket service not available")
    
    tables = socket_service.get_connection_tables()
    logger.info("Connection tables queried")
    
    return {
        "success": True,
        "data": tables
    }


@router.post("/connections/disconnect")
async def disconnect_connection(data: Dict[str, Any], api_key: Any = Depends(verify_api_key)):
    """
    断开特定用户与特定项目的连接
    """
    item_uuid = data.get("item_uuid")
    user_uuid = data.get("user_uuid")
    
    if not item_uuid or not user_uuid:
        raise HTTPException(status_code=400, detail="Missing item_uuid or user_uuid")
    
    from core import get_socket_service
    socket_service = get_socket_service()
    if not socket_service:
        raise HTTPException(status_code=500, detail="Socket service not available")
    
    disconnected = await socket_service.disconnect_user_from_item(item_uuid, user_uuid)
    
    if disconnected:
        logger.info(f"Disconnected user {user_uuid} from item {item_uuid}")
        return {
            "success": True,
            "message": "Connection disconnected successfully"
        }
    else:
        logger.warning(f"Failed to disconnect user {user_uuid} from item {item_uuid}")
        return {
            "success": False,
            "message": "Failed to disconnect connection"
        }
