import asyncio
import socketio
import queue
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime
from core import config, daemon_conn_pool
from utils.logger import logger
from service.room_manager import room_manager, Subscriber


class SocketService:
    """
    Socket.IO连接池管理 - 按 UPDATE.MD 和 pool.md 规范使用 Room 机制
    
    核心设计：
    1. 使用 DaemonConnPool 管理三类连接
    2. 使用 DaemonRoomManager 管理 Room 和订阅者
    3. 区分 permanent（Backend）和 temporary（Browser）订阅者
    4. 每个 item_uuid 对应一个 Room
    
    连接池表（由 DaemonConnPool 管理）：
    1. backend_main_conn_pool: Backend主连接池
    2. browser_terminal_conn_pool: 浏览器终端连接池
    3. backend_room_listen_conn_pool: Backend Room监听连接池
    """
    def __init__(self, sio: socketio.Server):
        self.sio = sio
        self.item_tokens: Dict[str, str] = {}
        self.lock = threading.Lock()
        self._broadcast_queues: Dict[str, queue.Queue] = {}
        self._broadcast_threads: Dict[str, threading.Thread] = {}
        self._running = True

    def get_room_name(self, item_uuid: str) -> str:
        return item_uuid

    async def join_item_room(self, sid: str, item_uuid: str, subscriber_type: str, user_uuid: str = "unknown"):
        room_id = self.get_room_name(item_uuid)
        
        await self.sio.enter_room(sid, room_id)
        
        ip = "unknown"
        browser_conn = daemon_conn_pool.get_browser_terminal_conn(item_uuid, sid)
        if browser_conn:
            ip = browser_conn.ip or "unknown"
        
        subscriber = Subscriber(
            sid=sid,
            subscriber_type=subscriber_type,
            user_uuid=user_uuid,
            ip=ip
        )
        room_manager.add_subscriber(room_id, subscriber)
        
        logger.info(f"[Room] SID {sid[:16]}... joined room {room_id} as {subscriber_type}")

    async def leave_item_room(self, sid: str, item_uuid: str):
        room_id = self.get_room_name(item_uuid)
        await self.sio.leave_room(sid, room_id)
        room_manager.remove_subscriber(room_id, sid)
        logger.info(f"[Room] SID {sid[:16]}... left room {room_id}")

    async def handle_disconnect(self, sid: str):
        logger.info(f"\n{'='*60}")
        logger.info(f"[Disconnect] Socket断开处理: {sid[:16]}...")
        logger.info(f"{'='*60}")
        
        item_uuid_to_notify = None
        
        backend_main_conn = daemon_conn_pool.get_backend_main_conn(config.get("API_KEY"))
        if backend_main_conn and backend_main_conn.conn_id == sid:
            daemon_conn_pool.remove_backend_main_conn(config.get("API_KEY"))
            logger.info(f"  类型: Backend主连接")
        
        room_listen_conns = daemon_conn_pool.get_all_backend_room_listen_conns()
        for conn in room_listen_conns:
            if conn.conn_id == sid:
                daemon_conn_pool.remove_backend_room_listen_conn(conn.item_uuid)
                await self.leave_item_room(sid, conn.item_uuid)
                item_uuid_to_notify = conn.item_uuid
                logger.info(f"  类型: Backend Room监听连接, Item: {conn.item_uuid}")
        
        for item_uuid, conns in daemon_conn_pool.get_all_browser_terminal_conns().items():
            for conn in conns:
                if conn.sid == sid:
                    daemon_conn_pool.remove_browser_terminal_conn(item_uuid, sid)
                    logger.info(f"  类型: Browser终端连接, Item: {item_uuid}, User: {conn.user_uuid}")
                    await self.leave_item_room(sid, item_uuid)
                    
                    room_info = room_manager.get_room_info(item_uuid)
                    if room_info:
                        total = room_info['permanent_count'] + room_info['temporary_count']
                        if total > 0:
                            item_uuid_to_notify = item_uuid
        
        if item_uuid_to_notify:
            await self.notify_connection_update(item_uuid_to_notify)
        
        logger.info(f"{'='*60}\n")

    async def broadcast_to_terminal(self, item_uuid: str, event: str, data: Any):
        room = self.get_room_name(item_uuid)
        try:
            room_info = room_manager.get_room_info(room)
            if not room_info:
                logger.debug(f"[SocketService] Skip broadcast to room '{room}': no room")
                return

            subscriber_count = room_info.get('permanent_count', 0) + room_info.get('temporary_count', 0)
            if subscriber_count <= 0:
                logger.debug(f"[SocketService] Skip broadcast to room '{room}': no subscribers")
                return

            logger.info(f"[SocketService] Broadcasting to room '{room}': event={event}")
            logger.info(f"[SocketService] Room info: permanent={room_info.get('permanent_count', 0)}, temporary={room_info.get('temporary_count', 0)}")
            logger.info(f"[SocketService] Permanent subscribers: {room_info.get('permanent', [])}")
            await self.sio.emit(event, data, room=room)
            logger.info(f"[SocketService] Broadcast to room '{room}' completed")
        except Exception as e:
            logger.error(f"Failed to broadcast to room {room}: {e}")

    def sync_broadcast(self, item_uuid: str, event: str, data: Any):
        if item_uuid not in self._broadcast_queues:
            with self.lock:
                if item_uuid not in self._broadcast_queues:
                    self._broadcast_queues[item_uuid] = queue.Queue()
                    thread = threading.Thread(
                        target=self._broadcast_worker,
                        args=(item_uuid,),
                        daemon=True
                    )
                    thread.start()
                    self._broadcast_threads[item_uuid] = thread
        
        self._broadcast_queues[item_uuid].put((event, data))

    def _broadcast_worker(self, item_uuid: str):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            while self._running:
                try:
                    event, data = self._broadcast_queues[item_uuid].get(timeout=0.1)
                    loop.run_until_complete(
                        self.broadcast_to_terminal(item_uuid, event, data)
                    )
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Broadcast worker error for {item_uuid}: {e}")
        finally:
            loop.close()

    async def close_terminal_connections(self, item_uuid: str):
        room_id = self.get_room_name(item_uuid)
        sids = room_manager.destroy_room(room_id)
        
        daemon_conn_pool.remove_all_browser_terminal_conns(item_uuid)
        daemon_conn_pool.remove_backend_room_listen_conn(item_uuid)
        
        async def disconnect_in_background():
            for sid in sids:
                try:
                    await self.sio.leave_room(sid, room_id)
                    await asyncio.wait_for(self.sio.disconnect(sid), timeout=2.0)
                    logger.info(f"Disconnected socket: {sid[:16]}...")
                except Exception as e:
                    logger.error(f"Failed to disconnect {sid}: {e}")
        
        if sids:
            asyncio.create_task(disconnect_in_background())
            logger.info(f"Closing {len(sids)} connections for item {item_uuid}")
        
        return {}

    def get_terminal_connections(self, item_uuid: str) -> Dict[str, Dict[str, str]]:
        result = {}
        conns = daemon_conn_pool.get_browser_terminal_conns(item_uuid)
        for conn in conns:
            if conn.is_authenticated():
                result[conn.sid] = {
                    'user_uuid': conn.user_uuid or 'unknown',
                    'ip': conn.ip or 'unknown'
                }
        return result

    def get_all_connections(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        result = {}
        all_conns = daemon_conn_pool.get_all_browser_terminal_conns()
        
        for item_uuid, conns in all_conns.items():
            connections = {}
            for conn in conns:
                if conn.is_authenticated():
                    connections[conn.sid] = {
                        'user_uuid': conn.user_uuid or 'unknown',
                        'ip': conn.ip or 'unknown'
                    }
            if connections:
                result[item_uuid] = connections
        
        return result

    async def notify_connection_update(self, item_uuid: str):
        backend_conns = daemon_conn_pool.get_all_backend_main_conns()
        
        room_info = room_manager.get_room_info(item_uuid)
        
        if backend_conns and room_info:
            update_data = {
                "type": "item_update",
                "item_uuid": item_uuid,
                "room_info": room_info,
                "item_connections": self.get_terminal_connections(item_uuid)
            }
            
            for conn in backend_conns:
                if conn.is_connected() and conn.conn:
                    try:
                        await self.sio.emit("connection_update", update_data, to=conn.conn_id)
                    except Exception as e:
                        logger.error(f"Failed to notify Backend {conn.conn_id[:16]}...: {e}")

    def get_connection_count(self) -> int:
        rooms_info = room_manager.get_all_rooms_info()
        return sum(r['permanent_count'] + r['temporary_count'] for r in rooms_info.values())

    def get_terminal_count(self) -> int:
        return len(room_manager.get_all_rooms_info())

    def get_item_connections(self, item_uuid: str) -> Dict[str, Any]:
        return {
            'item_uuid': item_uuid,
            'connections': self.get_terminal_connections(item_uuid)
        }

    async def disconnect_user_from_item(self, item_uuid: str, user_uuid: str = None, ip_address: str = None) -> Dict[str, Any]:
        conns = daemon_conn_pool.get_browser_terminal_conns(item_uuid)
        
        sids_to_disconnect = []
        for conn in conns:
            match = False
            if user_uuid and ip_address:
                match = conn.user_uuid == user_uuid and conn.ip == ip_address
            elif user_uuid:
                match = conn.user_uuid == user_uuid
            elif ip_address:
                match = conn.ip == ip_address
            
            if match:
                sids_to_disconnect.append(conn.sid)
        
        for sid in sids_to_disconnect:
            try:
                await self.leave_item_room(sid, item_uuid)
                await self.sio.disconnect(sid)
                daemon_conn_pool.remove_browser_terminal_conn(item_uuid, sid)
            except Exception as e:
                logger.error(f"Failed to disconnect {sid}: {e}")
        
        return self.get_terminal_connections(item_uuid)

    async def disconnect_by_ip(self, item_uuid: str, ip_address: str) -> Dict[str, Any]:
        return await self.disconnect_user_from_item(item_uuid, ip_address=ip_address)

    def get_room_manager(self):
        return room_manager

    def store_item_token(self, item_uuid: str, token: str):
        with self.lock:
            self.item_tokens[item_uuid] = token

    def get_item_token(self, item_uuid: str) -> Optional[str]:
        return self.item_tokens.get(item_uuid)

    def remove_item_token(self, item_uuid: str):
        with self.lock:
            self.item_tokens.pop(item_uuid, None)
