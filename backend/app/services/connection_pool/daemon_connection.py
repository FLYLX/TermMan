import socketio
import asyncio
import uuid
from typing import Callable, Dict, Any, Optional
from datetime import datetime
from ..protocol import ProtocolEvents
from .connection_models import ConnectionStatus, DaemonConfig
import logging

logger = logging.getLogger(__name__)


class DaemonConnection:
    """
    单个Daemon节点的WebSocket连接封装
    
    使用WebSocket进行所有通信：
    - 发送请求并等待响应
    - 接收事件（如stdout）
    - 维护连接状态
    """
    def __init__(self, config: DaemonConfig):
        self.config = config
        self.status = ConnectionStatus.DISCONNECTED
        
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=2,
            reconnection_delay_max=10,
            logger=False,
            engineio_logger=False
        )
        
        self.callbacks: Dict[str, Callable] = {}
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.last_heartbeat = None
        
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        @self.sio.event
        def connect():
            self.status = ConnectionStatus.CONNECTED
            self.last_heartbeat = datetime.now()
            logger.info(f"[WebSocket] Connected to {self.config.base_url}")
            
            if "connect" in self.callbacks:
                self.callbacks["connect"]()

        @self.sio.event
        def disconnect():
            self.status = ConnectionStatus.DISCONNECTED
            logger.info(f"[WebSocket] Disconnected from {self.config.base_url}")
            
            for future in self.pending_requests.values():
                if not future.done():
                    future.set_exception(Exception("Connection disconnected"))
            self.pending_requests.clear()
            
            if "disconnect" in self.callbacks:
                self.callbacks["disconnect"]()

        @self.sio.on("auth")
        def on_auth(data):
            if data.get("success"):
                logger.info(f"[WebSocket] Authenticated with daemon: {self.config.base_url}")
                self._sync_all_connections()
            else:
                logger.error(f"[WebSocket] Authentication failed: {data.get('message')}")

        @self.sio.on("terminal/start")
        def on_terminal_start(data):
            self._handle_response("terminal/start", data)

        @self.sio.on("terminal/stop")
        def on_terminal_stop(data):
            self._handle_response("terminal/stop", data)

        @self.sio.on("terminal/restart")
        def on_terminal_restart(data):
            self._handle_response("terminal/restart", data)

        @self.sio.on("terminal/status")
        def on_terminal_status(data):
            self._handle_response("terminal/status", data)

        @self.sio.on("terminal/list")
        def on_terminal_list(data):
            self._handle_response("terminal/list", data)

        @self.sio.on("connections/get")
        def on_connections_get(data):
            self._handle_response("connections/get", data)

        @self.sio.on("connections/get_all")
        def on_connections_get_all(data):
            self._handle_response("connections/get_all", data)

        @self.sio.on("connections/disconnect")
        def on_connections_disconnect(data):
            self._handle_response("connections/disconnect", data)

        @self.sio.on("connection_update")
        def on_connection_update(data):
            if "connection_update" in self.callbacks:
                self.callbacks["connection_update"](data)

        @self.sio.on("stream")
        def on_stream(data):
            if ProtocolEvents.INSTANCE_STDOUT in self.callbacks:
                self.callbacks[ProtocolEvents.INSTANCE_STDOUT](data)

        @self.sio.on("terminal_connected")
        def on_terminal_connected(data):
            logger.info(f"[WebSocket] Terminal connected: {data.get('item_uuid')}")

        @self.sio.on("auth_error")
        def on_auth_error(data):
            logger.error(f"[WebSocket] Auth error: {data.get('message')}")

    def _handle_response(self, event: str, data: Dict[str, Any]):
        request_id = data.get("request_id")
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests.pop(request_id)
            if not future.done():
                future.set_result(data)
        else:
            if event in self.callbacks:
                self.callbacks[event](data)

    def _generate_request_id(self) -> str:
        return str(uuid.uuid4())

    async def _emit_and_wait(self, event: str, data: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        if self.status != ConnectionStatus.CONNECTED:
            return {"success": False, "error": "Not connected to daemon"}
        
        request_id = self._generate_request_id()
        data["request_id"] = request_id
        
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        
        try:
            self.sio.emit(event, data)
            
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.pending_requests.pop(request_id, None)
            return {"success": False, "error": "Request timeout"}
        except Exception as e:
            self.pending_requests.pop(request_id, None)
            return {"success": False, "error": str(e)}

    def connect(self) -> bool:
        try:
            self.sio.connect(
                self.config.base_url,
                transports=["websocket"],
                auth={"api_key": self.config.api_key}
            )
            
            self.sio.emit("auth", {
                "backend_id": f"{self.config.ip}:{self.config.api_key[:8]}"
            })
            
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.config.base_url}: {str(e)}")
            self.status = ConnectionStatus.ERROR
            return False

    def disconnect(self):
        try:
            self.sio.disconnect()
        except Exception:
            pass
        self.status = ConnectionStatus.DISCONNECTED

    def on(self, event: str, callback: Callable):
        self.callbacks[event] = callback

    def is_connected(self) -> bool:
        return self.status == ConnectionStatus.CONNECTED

    def get_status(self) -> ConnectionStatus:
        return self.status

    async def terminal_start(self, user_uuid: str, item_uuid: str, working_directory: str = None, command: str = None) -> Dict[str, Any]:
        data = {
            "user_uuid": user_uuid,
            "item_uuid": item_uuid
        }
        if working_directory:
            data["working_directory"] = working_directory
        if command:
            data["command"] = command
        
        return await self._emit_and_wait("terminal/start", data)

    async def terminal_stop(self, item_uuid: str) -> Dict[str, Any]:
        return await self._emit_and_wait("terminal/stop", {
            "item_uuid": item_uuid
        })

    async def terminal_restart(self, item_uuid: str, user_uuid: str = None, working_directory: str = None, command: str = None) -> Dict[str, Any]:
        data = {"item_uuid": item_uuid}
        if user_uuid:
            data["user_uuid"] = user_uuid
        if working_directory:
            data["working_directory"] = working_directory
        if command:
            data["command"] = command
        
        return await self._emit_and_wait("terminal/restart", data)

    async def terminal_status(self, item_uuid: str) -> Dict[str, Any]:
        return await self._emit_and_wait("terminal/status", {
            "item_uuid": item_uuid
        })

    async def terminal_list(self) -> Dict[str, Any]:
        return await self._emit_and_wait("terminal/list", {})

    async def get_connections(self, item_uuid: str) -> Dict[str, Any]:
        return await self._emit_and_wait("connections/get", {
            "item_uuid": item_uuid
        })

    async def get_all_connections(self) -> Dict[str, Any]:
        return await self._emit_and_wait("connections/get_all", {})

    def _sync_all_connections(self):
        import threading
        def run_sync():
            try:
                asyncio.run(self._do_sync_all_connections())
            except Exception as e:
                logger.error(f"[WebSocket] Failed to sync all connections: {str(e)}")
        
        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()

    async def _do_sync_all_connections(self):
        try:
            result = await self.get_all_connections()
            if result.get("success"):
                connections = result.get("connections", {})
                
                logger.info(f"\n{'@'*80}")
                logger.info(f"[DaemonConnection] 收到 Daemon 全量连接池数据")
                logger.info(f"{'@'*80}")
                logger.info(f"  来源: {self.config.base_url}")
                logger.info(f"  Items 数量: {len(connections)}")
                
                if connections:
                    logger.info(f"  连接池详情:")
                    for item_uuid, item_conns in connections.items():
                        logger.info(f"    Item: {item_uuid}")
                        if item_conns:
                            for sid, conn_info in item_conns.items():
                                logger.info(f"      - SID: {sid[:16]}... | User: {conn_info.get('user_uuid', 'unknown')} | IP: {conn_info.get('ip', 'unknown')}")
                        else:
                            logger.info(f"      - 无连接")
                
                if "connection_update" in self.callbacks:
                    self.callbacks["connection_update"]({
                        "type": "full_sync",
                        "connections": connections
                    })
                    logger.info(f"  [OK] 已触发 connection_update 回调")
                
                logger.info(f"{'@'*80}\n")
        except Exception as e:
            logger.error(f"[WebSocket] Failed to sync all connections: {str(e)}")

    async def disconnect_connection(self, item_uuid: str, user_uuid: str = None, ip_address: str = None) -> Dict[str, Any]:
        data = {"item_uuid": item_uuid}
        if user_uuid:
            data["user_uuid"] = user_uuid
        if ip_address:
            data["ip_address"] = ip_address
        
        return await self._emit_and_wait("connections/disconnect", data)

    def emit(self, event: str, data: Any) -> bool:
        if self.status != ConnectionStatus.CONNECTED:
            return False
        try:
            self.sio.emit(event, data)
            return True
        except Exception:
            return False

    def _run_async(self, coro):
        """同步运行异步协程"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def terminal_start_http(self, user_uuid: str, item_uuid: str, working_directory: str = None, command: str = None) -> Dict[str, Any]:
        """
        启动终端 - 同步方法
        
        返回:
            success: 是否成功
            item_uuid: 终端UUID
            token: 访问令牌
            message: 消息
        """
        return self._run_async(self.terminal_start(user_uuid, item_uuid, working_directory, command))

    def terminal_stop_http(self, item_uuid: str) -> Dict[str, Any]:
        """
        停止终端 - 同步方法
        
        返回:
            success: 是否成功
            item_uuid: 终端UUID
            message: 消息
        """
        return self._run_async(self.terminal_stop(item_uuid))

    def terminal_restart_http(self, item_uuid: str, user_uuid: str = None, working_directory: str = None, command: str = None) -> Dict[str, Any]:
        """
        重启终端 - 同步方法
        """
        return self._run_async(self.terminal_restart(item_uuid, user_uuid, working_directory, command))

    def terminal_status_http(self, item_uuid: str) -> Dict[str, Any]:
        """
        查询终端状态 - 同步方法
        """
        return self._run_async(self.terminal_status(item_uuid))

    def terminal_list_http(self) -> Dict[str, Any]:
        """
        获取终端列表 - 同步方法
        """
        return self._run_async(self.terminal_list())

    def get_connections_http(self, item_uuid: str) -> Dict[str, Any]:
        """
        获取指定item的连接池 - 同步方法
        
        返回:
            success: 是否成功
            item_uuid: 终端UUID
            connections: 连接池表 {sid: {user_uuid, ip}}
        """
        return self._run_async(self.get_connections(item_uuid))

    def get_all_connections_http(self) -> Dict[str, Any]:
        """
        获取所有连接池 - 同步方法
        
        返回:
            success: 是否成功
            connections: 所有连接池表
        """
        return self._run_async(self.get_all_connections())

    def disconnect_connection_http(self, item_uuid: str, user_uuid: str = None, ip_address: str = None) -> Dict[str, Any]:
        """
        断开指定连接 - 同步方法
        
        返回:
            success: 是否成功
            item_uuid: 终端UUID
            message: 消息
            connections: 更新后的连接池表
        """
        return self._run_async(self.disconnect_connection(item_uuid, user_uuid, ip_address))
