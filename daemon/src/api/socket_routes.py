import hashlib
import hmac
import socketio
import time
import uuid as uuid_lib
import requests
import re
from service.socket_service import SocketService
from service.terminal_manager import terminal_manager
from service.job_runner import job_runner
from service.room_manager import room_manager
from core import config, daemon_conn_pool
from utils.logger import logger

sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")
socket_service = SocketService(sio)

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import set_socket_service
set_socket_service(socket_service)


def _normalize_terminal_write_payload(command: str) -> str:
    if not command:
        return ""

    if command == "\x03":
        return command

    if command.endswith(("\n", "\r")):
        return command

    return f"{command}\n"


def _terminal_completion_token_start(command: str, cursor: int) -> int:
    token_start = 0
    quote = None
    escaped = False

    for index, char in enumerate(command[:cursor]):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char.isspace():
            token_start = index + 1

    return token_start


def _unescape_terminal_path(value: str) -> str:
    result = []
    escaped = False
    for char in value:
        if escaped:
            result.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)


def _escape_terminal_path(value: str) -> str:
    return re.sub(r"([\s\\'\"`$&;|<>*?()\[\]{}!])", r"\\\1", value)


def _complete_terminal_command(command: str, cursor: int, current_workdir: str) -> dict:
    cursor = max(0, min(cursor, len(command)))
    token_start = _terminal_completion_token_start(command, cursor)
    raw_token = command[token_start:cursor]
    quote = raw_token[0] if raw_token.startswith(("'", '"')) else ""
    token = raw_token[1:] if quote else _unescape_terminal_path(raw_token)

    slash_index = token.rfind("/")
    if slash_index >= 0:
        directory_fragment = token[: slash_index + 1]
        name_prefix = token[slash_index + 1 :]
    else:
        directory_fragment = ""
        name_prefix = token

    if directory_fragment.startswith("~"):
        search_directory = os.path.expanduser(directory_fragment)
    elif os.path.isabs(directory_fragment):
        search_directory = directory_fragment
    else:
        search_directory = os.path.join(current_workdir, directory_fragment)

    candidates = []
    try:
        for entry in os.scandir(search_directory or current_workdir):
            if not name_prefix.startswith(".") and entry.name.startswith("."):
                continue
            if not entry.name.startswith(name_prefix):
                continue
            suffix = "/" if entry.is_dir(follow_symlinks=True) else ""
            candidates.append(f"{directory_fragment}{entry.name}{suffix}")
    except OSError:
        return {
            "success": True,
            "value": command,
            "cursor": cursor,
            "candidates": [],
        }

    candidates.sort()
    candidates = candidates[:100]
    if not candidates:
        return {
            "success": True,
            "value": command,
            "cursor": cursor,
            "candidates": [],
        }

    completion = os.path.commonprefix(candidates)
    if len(candidates) == 1:
        completion = candidates[0]

    rendered_completion = (
        f"{quote}{completion}" if quote else _escape_terminal_path(completion)
    )
    completed_command = (
        command[:token_start] + rendered_completion + command[cursor:]
    )
    completed_cursor = token_start + len(rendered_completion)

    return {
        "success": True,
        "value": completed_command,
        "cursor": completed_cursor,
        "candidates": candidates,
    }


def _verify_temp_token_locally(temp_token: str, item_uuid: str) -> dict:
    """HMAC tokens are verified with the daemon's own API_KEY — no backend
    callback needed. Returns None if the token is not in HMAC format."""
    parts = temp_token.split(".")
    if len(parts) != 4:
        return None
    token_item_uuid, user_id, expire_ts_raw, signature = parts
    if token_item_uuid != item_uuid:
        return {"success": False, "error": "Token item_uuid mismatch"}
    try:
        expire_ts = int(expire_ts_raw)
    except ValueError:
        return {"success": False, "error": "Invalid token expiry"}
    if time.time() > expire_ts:
        return {"success": False, "error": "Token expired"}
    payload = f"{token_item_uuid}.{user_id}.{expire_ts_raw}"
    expected = hmac.new(
        config.get("API_KEY").encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return {"success": False, "error": "Invalid token signature"}
    return {"success": True, "user_id": user_id}


def verify_temp_token(temp_token: str, item_uuid: str) -> dict:
    """HMAC 本地验签，无需回调 Backend。"""
    result = _verify_temp_token_locally(temp_token, item_uuid)
    if result is None:
        return {"success": False, "error": "Invalid token format"}
    if result.get("success"):
        logger.info(f"[Auth] Temp token verified: item={item_uuid}, user={result.get('user_id')}")
    else:
        logger.warning(f"[Auth] Temp token verification failed: {result.get('error')}")
    return result


@sio.event
async def connect(sid, environ, auth=None):
    # Capture the main ASGI event loop for broadcast workers
    from core import get_socket_service
    _ss = get_socket_service()
    if _ss:
        _ss.store_main_loop()
    ip_address = environ.get('REMOTE_ADDR', 'unknown')
    
    if auth and "api_key" in auth:
        if auth["api_key"] == config.get("API_KEY"):
            logger.info(f"[WebSocket] Backend connected: {sid}, IP: {ip_address}")
            return True
    
    if auth and "temp_token" in auth and "item_uuid" in auth:
        temp_token = auth["temp_token"]
        item_uuid = auth["item_uuid"]
        
        browser_conn = daemon_conn_pool.create_browser_terminal_conn("pending", sid)
        browser_conn.ip = ip_address
        logger.info(f"[WebSocket] Browser connected (pending temp token auth): {sid}, IP: {ip_address}, item={item_uuid}")
        
        result = verify_temp_token(temp_token, item_uuid)
        
        if result.get("success"):
            user_uuid = result.get("user_id")
            
            daemon_conn_pool.remove_browser_terminal_conn("pending", sid)
            
            browser_conn = daemon_conn_pool.create_browser_terminal_conn(item_uuid, sid)
            browser_conn.set_authenticated(user_uuid)
            browser_conn.ip = ip_address
            
            if not room_manager.room_exists(item_uuid):
                room_manager.create_room(item_uuid)
            
            await socket_service.join_item_room(sid, item_uuid, "browser", user_uuid)
            
            room_info = room_manager.get_room_info(item_uuid)
            
            logger.info(f"[WebSocket] Browser authenticated via temp token: {sid}, user={user_uuid}, item={item_uuid}")
            
            await sio.emit("terminal_connected", {
                "item_uuid": item_uuid,
                "subscriber_type": "browser",
                "room_info": room_info,
                "user_uuid": user_uuid
            }, to=sid)
            
            await socket_service.notify_connection_update(item_uuid)
            
            return True
        else:
            logger.warning(f"[WebSocket] Temp token auth failed: {sid}, error={result.get('error')}")
            await sio.emit("auth_error", {"message": result.get("error", "Token verification failed")}, to=sid)
            return False
    
    if auth and "access_token" in auth:
        browser_conn = daemon_conn_pool.create_browser_terminal_conn("pending", sid)
        browser_conn.ip = ip_address
        logger.info(f"[WebSocket] Browser connected (pending auth): {sid}, IP: {ip_address}")
        return True
    
    logger.warning(f"[WebSocket] Connection rejected: {sid}, IP: {ip_address}, invalid auth")
    return False


@sio.event
async def disconnect(sid):
    await socket_service.handle_disconnect(sid)


@sio.on("auth")
async def on_auth(sid, data):
    backend_id = data.get("backend_id", "unknown")
    api_key = config.get("API_KEY")
    
    existing_conn = daemon_conn_pool.get_backend_main_conn(api_key)
    if existing_conn and existing_conn.conn_id:
        logger.info(f"[WebSocket] Backend {backend_id} already connected, disconnecting old connection")
        try:
            await sio.disconnect(existing_conn.conn_id)
        except Exception as e:
            logger.warning(f"Failed to disconnect old connection: {e}")
    
    backend_conn = daemon_conn_pool.create_backend_main_conn(api_key)
    backend_conn.set_connected(None, sid, auth_token=None)
    
    logger.info(f"[WebSocket] Backend authenticated: {sid}, backend_id: {backend_id}")
    
    await sio.emit("auth", {"success": True, "message": "Authentication successful"}, to=sid)
    
    all_connections = socket_service.get_all_connections()
    rooms_info = room_manager.get_all_rooms_info()
    
    logger.info(f"[Daemon] Backend认证成功，发送全量连接池数据: {len(rooms_info)} Rooms")
    
    await sio.emit("connection_update", {
        "type": "full_sync",
        "connections": all_connections,
        "rooms": rooms_info
    }, to=sid)


@sio.on("verify_access_token")
async def on_verify_access_token(sid, data):
    from service.auth_service import auth_service
    
    access_token = data.get("access_token")
    item_uuid = data.get("item_uuid")
    request_id = data.get("request_id")
    
    result = auth_service.verify_access_token(access_token, item_uuid)
    result["request_id"] = request_id
    
    await sio.emit("verify_access_token", result, to=sid)


@sio.on("terminal/start")
async def on_terminal_start(sid, data):
    user_uuid = data.get("user_uuid")
    item_uuid = data.get("item_uuid")
    item_title = data.get("item_title")
    working_directory = data.get("working_directory")
    command = data.get("command")
    request_id = data.get("request_id")

    if item_title:
        from service.item_path_service import item_path_service

        item_path_service.register_item_title(item_uuid, item_title)
    
    logger.info(f"[WebSocket] Terminal start: item={item_uuid}, user={user_uuid}")
    
    if not user_uuid or not item_uuid:
        await sio.emit("terminal/start", {
            "success": False,
            "error": "Missing user_uuid or item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    existing_terminal = terminal_manager.get_terminal(item_uuid)
    if existing_terminal and existing_terminal.status in ("running", "waiting_backend", "starting"):
        token = socket_service.get_item_token(item_uuid)
        if not token:
            token = str(uuid_lib.uuid4())
            socket_service.store_item_token(item_uuid, token)
        
        await sio.emit("terminal/start", {
            "success": True,
            "item_uuid": item_uuid,
            "token": token,
            "already_running": True,
            "message": "该item终端已在运行中",
            "request_id": request_id
        }, to=sid)
        return
    if existing_terminal and existing_terminal.status in ("stopped", "error"):
        logger.info(f"[WebSocket] Removing dead terminal for item={item_uuid} (status={existing_terminal.status})")
        terminal_manager.remove_terminal(item_uuid)
    
    room_manager.create_room(item_uuid)
    
    token = str(uuid_lib.uuid4())
    terminal_manager.create_terminal(user_uuid, token, working_directory, command, item_uuid)
    
    socket_service.store_item_token(item_uuid, token)
    
    if not terminal_manager.start_terminal(item_uuid):
        room_manager.destroy_room(item_uuid)
        socket_service.remove_item_token(item_uuid)
        await sio.emit("terminal/start", {
            "success": False,
            "error": "Failed to start terminal",
            "request_id": request_id
        }, to=sid)
        return
    
    logger.info(f"[WebSocket] Terminal started: {item_uuid}")
    
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
    
    logger.info(f"[WebSocket] Terminal stop: item={item_uuid}")
    
    if not item_uuid:
        await sio.emit("terminal/stop", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    terminal = terminal_manager.get_terminal(item_uuid)
    if not terminal:
        await sio.emit("terminal/stop", {
            "success": True,
            "item_uuid": item_uuid,
            "message": "item未启动",
            "request_id": request_id
        }, to=sid)
        return
    
    socket_service.remove_item_token(item_uuid)
    terminal_manager.stop_terminal(item_uuid)
    
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
    
    logger.info(f"[WebSocket] Terminal restart: item={item_uuid}")
    
    if not item_uuid:
        await sio.emit("terminal/restart", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    terminal = terminal_manager.get_terminal(item_uuid)
    if terminal:
        socket_service.remove_item_token(item_uuid)
        terminal_manager.stop_terminal(item_uuid)
        await socket_service.close_terminal_connections(item_uuid)
    
    token = str(uuid_lib.uuid4())
    
    room_manager.create_room(item_uuid)
    
    if user_uuid:
        terminal_manager.create_terminal(user_uuid, token, working_directory, command, item_uuid)
        socket_service.store_item_token(item_uuid, token)
        
        if not terminal_manager.start_terminal(item_uuid):
            room_manager.destroy_room(item_uuid)
            await sio.emit("terminal/restart", {
                "success": False,
                "error": "Failed to start terminal",
                "request_id": request_id
            }, to=sid)
            return
    
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
    room_info = room_manager.get_room_info(item_uuid)
    room_connection = daemon_conn_pool.get_backend_room_listen_conn(item_uuid)
    backend_room_connected = bool(
        room_info
        and int(room_info.get("permanent_count") or 0) > 0
        and room_connection
        and room_connection.is_connected()
    )
    status["room_info"] = room_info
    status["backend_room_connected"] = backend_room_connected
    status["active"] = bool(
        str(status.get("status") or "") in {"running", "waiting_backend"}
        and backend_room_connected
    )
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
    room_info = room_manager.get_room_info(item_uuid)
    
    await sio.emit("connections/get", {
        "success": True,
        "item_uuid": result['item_uuid'],
        "connections": result['connections'],
        "room_info": room_info,
        "request_id": request_id
    }, to=sid)


@sio.on("connections/get_all")
async def on_connections_get_all(sid, data):
    request_id = data.get("request_id")
    
    all_connections = socket_service.get_all_connections()
    rooms_info = room_manager.get_all_rooms_info()
    
    await sio.emit("connections/get_all", {
        "success": True,
        "connections": all_connections,
        "rooms": rooms_info,
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
    
    connections = await socket_service.disconnect_user_from_item(item_uuid, user_uuid, ip_address)
    
    await sio.emit("connections/disconnect", {
        "success": True,
        "item_uuid": item_uuid,
        "message": "连接已断开",
        "connections": connections,
        "request_id": request_id
    }, to=sid)


@sio.on("terminal/connect")
async def on_terminal_connect(sid, data):
    from service.auth_service import auth_service
    
    item_uuid = data.get("item_uuid")
    token = data.get("token")
    access_token = data.get("access_token")
    user_uuid = data.get("user_uuid", "unknown")
    subscriber_type = data.get("subscriber_type", "browser")

    logger.info(f"[Connect] 终端连接请求: item={item_uuid}, user={user_uuid}, type={subscriber_type}")
    
    if access_token:
        if not item_uuid:
            await sio.emit("auth_error", {"message": "Missing item_uuid"}, to=sid)
            return
        
        result = auth_service.verify_access_token(access_token, item_uuid)
        
        if not result["success"]:
            await sio.emit("auth_error", {"message": result["error"]}, to=sid)
            return
        
        user_uuid = result["user_uuid"]
        subscriber_type = "browser"
        
        pending_conn = daemon_conn_pool.get_browser_terminal_conn("pending", sid)
        if pending_conn:
            daemon_conn_pool.remove_browser_terminal_conn("pending", sid)
        
        browser_conn = daemon_conn_pool.create_browser_terminal_conn(item_uuid, sid)
        browser_conn.set_authenticated(user_uuid)
    
    elif subscriber_type == "backend":
        if not item_uuid or not token:
            await sio.emit("auth_error", {"message": "Missing item_uuid or token"}, to=sid)
            return

        stored_token = socket_service.get_item_token(item_uuid)
        if not stored_token or stored_token != token:
            await sio.emit("auth_error", {"message": "Invalid token"}, to=sid)
            return
        
        room_listen_conn = daemon_conn_pool.create_backend_room_listen_conn(item_uuid)
        room_listen_conn.set_connected(None, sid)
        daemon_conn_pool._log_pool_state(f"Backend Room监听连接已建立: item={item_uuid}")
    
    else:
        if not item_uuid or not token:
            await sio.emit("auth_error", {"message": "Missing item_uuid or token"}, to=sid)
            return

        stored_token = socket_service.get_item_token(item_uuid)
        if not stored_token or stored_token != token:
            await sio.emit("auth_error", {"message": "Invalid token"}, to=sid)
            return
        
        pending_conn = daemon_conn_pool.get_browser_terminal_conn("pending", sid)
        if pending_conn:
            daemon_conn_pool.remove_browser_terminal_conn("pending", sid)
        
        browser_conn = daemon_conn_pool.create_browser_terminal_conn(item_uuid, sid)
        browser_conn.set_authenticated(user_uuid)

    if not room_manager.room_exists(item_uuid):
        logger.warning(f"Room {item_uuid} 不存在，创建新 Room")
        room_manager.create_room(item_uuid)

    await socket_service.join_item_room(sid, item_uuid, subscriber_type, user_uuid)

    room_info = room_manager.get_room_info(item_uuid)
    
    logger.info(f"[Connect] 连接成功: type={subscriber_type}, permanent={room_info['permanent_count']}, temporary={room_info['temporary_count']}")

    await sio.emit("terminal_connected", {
        "item_uuid": item_uuid,
        "subscriber_type": subscriber_type,
        "room_info": room_info
    }, to=sid)
    
    if subscriber_type == "backend":
        terminal_manager.notify_backend_connected(item_uuid)
        logger.info(f"[Connect] Notified terminal that Backend connected: {item_uuid}")
    
    await socket_service.notify_connection_update(item_uuid)


@sio.on("terminal/write")
async def on_terminal_write(sid, data):
    command = _normalize_terminal_write_payload(data.get("command", ""))
    if not command:
        return

    for item_uuid, conns in daemon_conn_pool.get_all_browser_terminal_conns().items():
        for conn in conns:
            if conn.sid == sid:
                if command == "\x03":
                    cancel_result = job_runner.cancel_job(item_uuid=item_uuid)
                    if cancel_result.get("success") or cancel_result.get("cancelled"):
                        socket_service.sync_broadcast(
                            item_uuid,
                            "stream",
                            {
                                "stdin": "^C\n",
                                "stdout": "\u540e\u53f0\u4efb\u52a1\u5df2\u4e2d\u65ad\u3002\n",
                                "stderr": "",
                                "source": "browser",
                                "job_cancelled": True,
                                "job_id": cancel_result.get("job_id", ""),
                            },
                        )
                        return
                terminal = terminal_manager.get_terminal(item_uuid)
                if terminal:
                    terminal.write(command)
                return
    
    room_listen_conns = daemon_conn_pool.get_all_backend_room_listen_conns()
    for conn in room_listen_conns:
        if conn.conn_id == sid:
            if command == "\x03":
                cancel_result = job_runner.cancel_job(item_uuid=conn.item_uuid)
                if cancel_result.get("success") or cancel_result.get("cancelled"):
                    socket_service.sync_broadcast(
                        conn.item_uuid,
                        "stream",
                        {
                            "stdin": "^C\n",
                            "stdout": "\u540e\u53f0\u4efb\u52a1\u5df2\u4e2d\u65ad\u3002\n",
                            "stderr": "",
                            "source": "backend",
                            "job_cancelled": True,
                            "job_id": cancel_result.get("job_id", ""),
                        },
                    )
                    return
            terminal = terminal_manager.get_terminal(conn.item_uuid)
            if terminal:
                terminal.write(command)
            return


@sio.on("terminal/complete")
async def on_terminal_complete(sid, data):
    for item_uuid, conns in daemon_conn_pool.get_all_browser_terminal_conns().items():
        if not any(conn.sid == sid for conn in conns):
            continue

        terminal = terminal_manager.get_terminal(item_uuid)
        if not terminal:
            return {"success": False, "error": "Terminal is not running"}

        command = str(data.get("command", ""))
        try:
            cursor = int(data.get("cursor", len(command)))
        except (TypeError, ValueError):
            cursor = len(command)
        return _complete_terminal_command(
            command,
            cursor,
            terminal.current_workdir(),
        )

    return {"success": False, "error": "Terminal connection was not found"}


@sio.on("item/subscribers")
async def on_item_subscribers(sid, data):
    item_uuid = data.get("item_uuid")
    request_id = data.get("request_id")
    
    if not item_uuid:
        await sio.emit("item/subscribers", {
            "success": False,
            "error": "Missing item_uuid",
            "request_id": request_id
        }, to=sid)
        return
    
    browser_conns = daemon_conn_pool.get_browser_terminal_conns(item_uuid)
    room_listen_conn = daemon_conn_pool.get_backend_room_listen_conn(item_uuid)
    room_info = room_manager.get_room_info(item_uuid)
    
    subscribers = []
    for conn in browser_conns:
        if conn.is_authenticated():
            subscribers.append({
                "sid": conn.sid[:16] + "...",
                "user_uuid": conn.user_uuid,
                "ip": conn.ip,
                "type": "browser",
                "join_time": conn.join_time,
                "last_active_time": conn.last_active_time
            })
    
    backend_connected = room_listen_conn and room_listen_conn.is_connected() if room_listen_conn else False
    
    await sio.emit("item/subscribers", {
        "success": True,
        "item_uuid": item_uuid,
        "subscribers": subscribers,
        "browser_count": len(subscribers),
        "backend_connected": backend_connected,
        "room_info": room_info,
        "request_id": request_id
    }, to=sid)
