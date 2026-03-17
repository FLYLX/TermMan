import socketio
from service.socket_service import SocketService
from service.terminal_manager import terminal_manager
from core import memory_store, config
from utils.logger import logger

sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")

socket_service = SocketService(sio)

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import set_socket_service
set_socket_service(socket_service)


@sio.event
async def connect(sid, environ, auth=None):
    ip_address = environ.get('REMOTE_ADDR', 'unknown')
    
    if auth and "api_key" in auth:
        if auth["api_key"] == config.get("API_KEY"):
            with socket_service.lock:
                socket_service.sid_to_ip[sid] = ip_address
            logger.info(f"[WebSocket] Backend connected: {sid}, IP: {ip_address}")
            return True
    
    logger.warning(f"[WebSocket] Connection rejected: {sid}, IP: {ip_address}, invalid auth")
    return False


@sio.event
async def disconnect(sid):
    await socket_service.handle_disconnect(sid)


@sio.on("auth")
async def on_auth(sid, data):
    backend_id = data.get("backend_id", "unknown")
    from datetime import datetime
    
    existing_sid = None
    with socket_service.lock:
        for old_sid, conn_info in socket_service.backend_connections.items():
            if conn_info.get("backend_id") == backend_id:
                existing_sid = old_sid
                break
    
    if existing_sid:
        logger.info(f"[WebSocket] Backend {backend_id} already connected with SID {existing_sid[:16]}..., disconnecting old connection")
        try:
            await sio.disconnect(existing_sid)
        except Exception as e:
            logger.warning(f"Failed to disconnect old connection: {e}")
            with socket_service.lock:
                if existing_sid in socket_service.backend_connections:
                    del socket_service.backend_connections[existing_sid]
    
    with socket_service.lock:
        socket_service.backend_connections[sid] = {
            "backend_id": backend_id,
            "ip": socket_service.sid_to_ip.get(sid, "unknown"),
            "connected_at": datetime.now().isoformat()
        }
    
    logger.info(f"[WebSocket] Backend authenticated: {sid}, backend_id: {backend_id}")
    
    await sio.emit("auth", {
        "success": True,
        "message": "Authentication successful"
    }, to=sid)
    
    socket_service._print_connection_tables(f"Backend Authenticated: {backend_id}")
    
    all_connections = socket_service.get_all_connections()
    
    logger.info(f"\n{'%'*80}")
    logger.info(f"[Daemon] Backend认证成功，发送全量连接池数据")
    logger.info(f"{'%'*80}")
    logger.info(f"  目标 Backend: {backend_id}")
    logger.info(f"  目标 SID: {sid[:16]}...")
    logger.info(f"  Items 数量: {len(all_connections)}")
    
    if all_connections:
        logger.info(f"  连接池详情:")
        for item_uuid, item_conns in all_connections.items():
            logger.info(f"    Item: {item_uuid}")
            if item_conns:
                for conn_sid, conn_info in item_conns.items():
                    logger.info(f"      - SID: {conn_sid[:16]}... | User: {conn_info.get('user_uuid', 'unknown')} | IP: {conn_info.get('ip', 'unknown')}")
            else:
                logger.info(f"      - 无连接")
    else:
        logger.info(f"  连接池详情: 无任何连接")
    
    await sio.emit("connection_update", {
        "type": "full_sync",
        "connections": all_connections
    }, to=sid)
    
    logger.info(f"  [OK] 已发送全量连接池数据")
    logger.info(f"{'%'*80}\n")


@sio.on("terminal/start")
async def on_terminal_start(sid, data):
    user_uuid = data.get("user_uuid")
    item_uuid = data.get("item_uuid")
    working_directory = data.get("working_directory")
    command = data.get("command")
    request_id = data.get("request_id")
    
    logger.info(f"[WebSocket] Terminal start request: item={item_uuid}, user={user_uuid}, request_id={request_id}")
    
    if not user_uuid or not item_uuid:
        await sio.emit("terminal/start", {
            "success": False,
            "error": "Missing user_uuid or item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    import uuid
    
    existing_terminal = terminal_manager.get_terminal(item_uuid)
    if existing_terminal:
        with socket_service.lock:
            token = socket_service.item_tokens.get(item_uuid)
            if not token:
                token = str(uuid.uuid4())
                socket_service.item_tokens[item_uuid] = token
        
        logger.info(f"[WebSocket] Terminal already running: {item_uuid}")
        await sio.emit("terminal/start", {
            "success": True,
            "item_uuid": item_uuid,
            "token": token,
            "message": "item已启动",
            "request_id": request_id
        }, to=sid)
        return
    
    token = str(uuid.uuid4())
    
    created_uuid = terminal_manager.create_terminal(user_uuid, token, working_directory, command, item_uuid)
    
    with socket_service.lock:
        socket_service.item_tokens[created_uuid] = token
    
    if not terminal_manager.start_terminal(item_uuid):
        await sio.emit("terminal/start", {
            "success": False,
            "error": "Failed to start terminal",
            "request_id": request_id
        }, to=sid)
        return
    
    logger.info(f"[WebSocket] Terminal started: {item_uuid}, token: {token}")
    
    socket_service._print_connection_tables(f"Terminal Started: {item_uuid}")
    
    await sio.emit("terminal/start", {
        "success": True,
        "item_uuid": item_uuid,
        "token": token,
        "message": "启动成功",
        "request_id": request_id
    }, to=sid)


@sio.on("terminal/stop")
async def on_terminal_stop(sid, data):
    item_uuid = data.get("item_uuid")
    request_id = data.get("request_id")
    
    logger.info(f"[WebSocket] Terminal stop request: item={item_uuid}, request_id={request_id}")
    
    if not item_uuid:
        await sio.emit("terminal/stop", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    terminal = terminal_manager.get_terminal(item_uuid)
    if not terminal:
        logger.info(f"[WebSocket] Terminal not found: {item_uuid}")
        await sio.emit("terminal/stop", {
            "success": True,
            "item_uuid": item_uuid,
            "message": "item未启动",
            "request_id": request_id
        }, to=sid)
        return
    
    with socket_service.lock:
        if item_uuid in socket_service.item_tokens:
            del socket_service.item_tokens[item_uuid]
    
    terminal_manager.stop_terminal(item_uuid)
    
    logger.info(f"[WebSocket] Terminal stopped: {item_uuid}")
    
    await socket_service.close_terminal_connections(item_uuid)
    
    await sio.emit("terminal/stop", {
        "success": True,
        "item_uuid": item_uuid,
        "message": "终端已成功停止",
        "request_id": request_id
    }, to=sid)


@sio.on("terminal/restart")
async def on_terminal_restart(sid, data):
    item_uuid = data.get("item_uuid")
    user_uuid = data.get("user_uuid")
    working_directory = data.get("working_directory")
    command = data.get("command")
    request_id = data.get("request_id")
    
    logger.info(f"[WebSocket] Terminal restart request: item={item_uuid}, request_id={request_id}")
    
    if not item_uuid:
        await sio.emit("terminal/restart", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    terminal = terminal_manager.get_terminal(item_uuid)
    if terminal:
        with socket_service.lock:
            if item_uuid in socket_service.item_tokens:
                del socket_service.item_tokens[item_uuid]
        terminal_manager.stop_terminal(item_uuid)
        await socket_service.close_terminal_connections(item_uuid)
    
    import uuid
    token = str(uuid.uuid4())
    
    if user_uuid:
        terminal_manager.create_terminal(user_uuid, token, working_directory, command, item_uuid)
        with socket_service.lock:
            socket_service.item_tokens[item_uuid] = token
        
        if not terminal_manager.start_terminal(item_uuid):
            await sio.emit("terminal/restart", {
                "success": False,
                "error": "Failed to start terminal",
                "request_id": request_id
            }, to=sid)
            return
    
    logger.info(f"[WebSocket] Terminal restarted: {item_uuid}")
    
    await sio.emit("terminal/restart", {
        "success": True,
        "item_uuid": item_uuid,
        "token": token,
        "message": "终端已成功重启",
        "request_id": request_id
    }, to=sid)


@sio.on("terminal/status")
async def on_terminal_status(sid, data):
    item_uuid = data.get("item_uuid")
    request_id = data.get("request_id")
    
    if not item_uuid:
        await sio.emit("terminal/status", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    terminal = terminal_manager.get_terminal(item_uuid)
    if not terminal:
        await sio.emit("terminal/status", {
            "success": False,
            "error": "Terminal not found",
            "request_id": request_id
        }, to=sid)
        return
    
    status = terminal.get_status()
    await sio.emit("terminal/status", {
        "success": True,
        "data": status,
        "request_id": request_id
    }, to=sid)


@sio.on("terminal/list")
async def on_terminal_list(sid, data):
    request_id = data.get("request_id")
    terminals = terminal_manager.get_all_terminals()
    await sio.emit("terminal/list", {
        "success": True,
        "count": len(terminals),
        "data": terminals,
        "request_id": request_id
    }, to=sid)


@sio.on("connections/get")
async def on_connections_get(sid, data):
    item_uuid = data.get("item_uuid")
    request_id = data.get("request_id")
    
    if not item_uuid:
        await sio.emit("connections/get", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    result = socket_service.get_item_connections(item_uuid)
    await sio.emit("connections/get", {
        "success": True,
        "item_uuid": result['item_uuid'],
        "connections": result['connections'],
        "request_id": request_id
    }, to=sid)


@sio.on("connections/get_all")
async def on_connections_get_all(sid, data):
    request_id = data.get("request_id")
    
    logger.info(f"\n{'$'*80}")
    logger.info(f"[Daemon] 收到 Backend 全量连接池查询请求")
    logger.info(f"{'$'*80}")
    logger.info(f"  请求来源 SID: {sid[:16]}...")
    logger.info(f"  Request ID: {request_id}")
    
    all_connections = socket_service.get_all_connections()
    
    logger.info(f"  返回 Items 数量: {len(all_connections)}")
    if all_connections:
        logger.info(f"  连接池详情:")
        for item_uuid, item_conns in all_connections.items():
            logger.info(f"    Item: {item_uuid}")
            if item_conns:
                for conn_sid, conn_info in item_conns.items():
                    logger.info(f"      - SID: {conn_sid[:16]}... | User: {conn_info.get('user_uuid', 'unknown')} | IP: {conn_info.get('ip', 'unknown')}")
            else:
                logger.info(f"      - 无连接")
    
    logger.info(f"{'$'*80}\n")
    
    await sio.emit("connections/get_all", {
        "success": True,
        "connections": all_connections,
        "request_id": request_id
    }, to=sid)


@sio.on("connections/disconnect")
async def on_connections_disconnect(sid, data):
    item_uuid = data.get("item_uuid")
    user_uuid = data.get("user_uuid")
    ip_address = data.get("ip_address")
    request_id = data.get("request_id")
    
    if not item_uuid:
        await sio.emit("connections/disconnect", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    if not user_uuid and not ip_address:
        await sio.emit("connections/disconnect", {
            "success": False,
            "error": "Missing user_uuid or ip_address",
            "request_id": request_id
        }, to=sid)
        return
    
    if user_uuid:
        connections = await socket_service.disconnect_user_from_item(item_uuid, user_uuid)
        logger.info(f"[WebSocket] Disconnected user {user_uuid} from item {item_uuid}")
    else:
        connections = await socket_service.disconnect_by_ip(item_uuid, ip_address)
        logger.info(f"[WebSocket] Disconnected ip {ip_address} from item {item_uuid}")
    
    await sio.emit("connections/disconnect", {
        "success": True,
        "item_uuid": item_uuid,
        "message": "连接已断开",
        "connections": connections,
        "request_id": request_id
    }, to=sid)


@sio.on("terminal/connect")
async def on_terminal_connect(sid, data):
    item_uuid = data.get("item_uuid")
    token = data.get("token")
    user_uuid = data.get("user_uuid", "unknown")

    logger.info(f"\n{'='*60}")
    logger.info(f"[Connect] 用户连接终端请求")
    logger.info(f"{'='*60}")
    logger.info(f"  SID: {sid}")
    logger.info(f"  Item UUID: {item_uuid}")
    logger.info(f"  User UUID: {user_uuid}")
    logger.info(f"  Token: {token[:16]}..." if token else "  Token: None")

    if not item_uuid or not token:
        logger.error(f"  [FAIL] 缺少 item_uuid 或 token")
        logger.info(f"{'='*60}\n")
        await sio.emit("auth_error", {"message": "Missing item_uuid or token"}, to=sid)
        return

    with socket_service.lock:
        stored_token = socket_service.item_tokens.get(item_uuid)
    
    if not stored_token or stored_token != token:
        logger.error(f"  [FAIL] Token验证失败")
        logger.info(f"    存储的Token: {stored_token[:16] if stored_token else 'None'}...")
        logger.info(f"{'='*60}\n")
        await sio.emit("auth_error", {"message": "Invalid token"}, to=sid)
        return

    with socket_service.lock:
        if item_uuid not in socket_service.connections:
            socket_service.connections[item_uuid] = {}
        ip_address = socket_service.sid_to_ip.get(sid, 'unknown')
        socket_service.connections[item_uuid][sid] = {
            "user_uuid": user_uuid,
            "ip": ip_address
        }
        socket_service.sid_to_item[sid] = item_uuid
        socket_service.sid_to_user[sid] = user_uuid

    logger.info(f"  [OK] 连接成功")
    logger.info(f"  IP: {ip_address}")
    logger.info(f"  当前Item连接数: {len(socket_service.connections[item_uuid])}")
    logger.info(f"{'='*60}")

    await sio.emit("terminal_connected", {"item_uuid": item_uuid}, to=sid)
    
    socket_service._print_connection_tables(f"用户连接终端: {user_uuid}@{ip_address}")
    
    logger.info(f"\n{'#'*60}")
    logger.info(f"[Connect] 触发连接池同步通知...")
    logger.info(f"{'#'*60}")
    await socket_service.notify_connection_update(item_uuid)


@sio.on("terminal/write")
async def on_terminal_write(sid, data):
    with socket_service.lock:
        if sid in socket_service.sid_to_item:
            item_uuid = socket_service.sid_to_item[sid]
            terminal = terminal_manager.get_terminal(item_uuid)
            if terminal:
                terminal.write(data.get("command", "") + "\n")


@sio.on("instance/stdout")
async def on_instance_stdout(sid, data):
    item_uuid = data.get("item_uuid")
    stdout = data.get("stdout")
    
    if item_uuid and stdout:
        await socket_service.broadcast_to_terminal(item_uuid, "stream", {"stdout": stdout})
