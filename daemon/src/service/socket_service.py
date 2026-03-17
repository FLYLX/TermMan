import socketio
from typing import Dict, Any, List
import threading
from datetime import datetime
from core import memory_store, config
from utils.logger import logger


class SocketService:
    """
    Socket.IO连接池管理 - 按 UPDATE.MD 简化版连接表
    
    维护三张表：
    1. Backend连接表: [sid -> {backend_id, ip}]
    2. Item-Token映射表: {item_uuid: token}
    3. Item-连接映射表: [item_uuid -> {sid -> {user_uuid, ip}}]
    """
    def __init__(self, sio: socketio.Server):
        self.sio = sio
        self.connections: Dict[str, Dict[str, Dict[str, str]]] = {}
        self.sid_to_item: Dict[str, str] = {}
        self.sid_to_user: Dict[str, str] = {}
        self.sid_to_ip: Dict[str, str] = {}
        self.backend_connections: Dict[str, Dict[str, str]] = {}
        self.item_tokens: Dict[str, str] = {}
        self.lock = threading.Lock()

    async def handle_disconnect(self, sid: str):
        logger.info(f"\n{'='*60}")
        logger.info(f"[Disconnect] Socket断开处理开始")
        logger.info(f"{'='*60}")
        logger.info(f"  断开的SID: {sid}")
        
        item_uuid_to_notify = None
        
        with self.lock:
            if sid in self.backend_connections:
                backend_info = self.backend_connections.pop(sid)
                logger.info(f"  类型: Backend连接")
                logger.info(f"  Backend ID: {backend_info.get('backend_id')}")
                logger.info(f"{'='*60}\n")
            
            elif sid in self.sid_to_item:
                item_uuid = self.sid_to_item.pop(sid)
                ip_address = self.sid_to_ip.get(sid, 'unknown')
                user_uuid = 'unknown'
                if sid in self.sid_to_user:
                    user_uuid = self.sid_to_user.pop(sid)
                
                if sid in self.sid_to_ip:
                    self.sid_to_ip.pop(sid)
                
                logger.info(f"  类型: 用户连接")
                logger.info(f"  Item UUID: {item_uuid}")
                logger.info(f"  User UUID: {user_uuid}")
                logger.info(f"  IP: {ip_address}")
                
                if item_uuid in self.connections:
                    if sid in self.connections[item_uuid]:
                        self.connections[item_uuid].pop(sid)
                        logger.info(f"  已从连接表移除")
                    
                    if not self.connections[item_uuid]:
                        del self.connections[item_uuid]
                        logger.info(f"  Item连接表已清空，删除Item")
                    else:
                        item_uuid_to_notify = item_uuid
                        logger.info(f"  Item剩余连接数: {len(self.connections[item_uuid])}")
                
                self._print_connection_tables(f"用户断开连接: {user_uuid}@{ip_address}")
            else:
                if sid in self.sid_to_ip:
                    ip_address = self.sid_to_ip.pop(sid)
                    logger.info(f"  类型: 未认证连接")
                    logger.info(f"  IP: {ip_address}")
                else:
                    logger.info(f"  类型: 未知连接")
                logger.info(f"{'='*60}\n")
        
        if item_uuid_to_notify:
            logger.info(f"  触发连接池同步通知...")
            await self.notify_connection_update(item_uuid_to_notify)

    async def broadcast_to_terminal(self, item_uuid: str, event: str, data: Any):
        with self.lock:
            if item_uuid in self.connections:
                for sid in self.connections[item_uuid].keys():
                    try:
                        await self.sio.emit(event, data, to=sid)
                    except Exception as e:
                        logger.error(f"Failed to broadcast to {sid}: {e}")

    def sync_broadcast(self, item_uuid: str, event: str, data: Any):
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.broadcast_to_terminal(item_uuid, event, data))
            else:
                loop.run_until_complete(self.broadcast_to_terminal(item_uuid, event, data))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.broadcast_to_terminal(item_uuid, event, data))
            finally:
                loop.close()

    async def send_to_terminal(self, item_uuid: str, event: str, data: Any):
        with self.lock:
            if item_uuid in self.connections and self.connections[item_uuid]:
                sid = list(self.connections[item_uuid].keys())[0]
                try:
                    await self.sio.emit(event, data, to=sid)
                    return True
                except Exception as e:
                    logger.error(f"Failed to send to {sid}: {e}")
        return False

    async def close_terminal_connections(self, item_uuid: str):
        sids_to_disconnect = []
        backend_connections = {}
        
        with self.lock:
            if item_uuid in self.connections:
                for sid, conn_info in list(self.connections[item_uuid].items()):
                    if conn_info.get('user_uuid') == 'backend':
                        backend_connections[sid] = conn_info
                    else:
                        sids_to_disconnect.append(sid)
                
                self.connections[item_uuid] = backend_connections
                
                if not self.connections[item_uuid]:
                    del self.connections[item_uuid]
        
        import asyncio
        async def disconnect_in_background():
            for sid in sids_to_disconnect:
                try:
                    await asyncio.wait_for(self.sio.disconnect(sid), timeout=2.0)
                    logger.info(f"Disconnected user socket: {sid}")
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout disconnecting {sid}")
                except Exception as e:
                    logger.error(f"Failed to disconnect {sid}: {e}")
        
        if sids_to_disconnect:
            asyncio.create_task(disconnect_in_background())
            logger.info(f"Closing {len(sids_to_disconnect)} user connections for item {item_uuid}, keeping {len(backend_connections)} backend connections")
        
        return backend_connections

    def get_terminal_connections(self, item_uuid: str) -> Dict[str, Dict[str, str]]:
        with self.lock:
            if item_uuid in self.connections:
                return self.connections[item_uuid].copy()
            return {}

    def get_all_connections(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        with self.lock:
            return self.connections.copy()

    async def notify_connection_update(self, item_uuid: str):
        """
        通知所有backend有新的socket连接更新
        
        Args:
            item_uuid: 发生变化的item UUID
        """
        with self.lock:
            item_connections = self.connections.get(item_uuid, {}).copy()
            backend_sids = list(self.backend_connections.keys())
        
        logger.info(f"\n{'#'*80}")
        logger.info(f"[ConnectionSync] 准备同步 Item 连接池到 Backend")
        logger.info(f"{'#'*80}")
        logger.info(f"  Item UUID: {item_uuid}")
        logger.info(f"  当前连接数: {len(item_connections)}")
        logger.info(f"  待通知Backend数: {len(backend_sids)}")
        
        if item_connections:
            logger.info(f"  连接详情:")
            for sid, conn_info in item_connections.items():
                logger.info(f"    - SID: {sid[:16]}... | User: {conn_info.get('user_uuid', 'unknown')} | IP: {conn_info.get('ip', 'unknown')}")
        else:
            logger.info(f"  连接详情: 无连接")
        
        if backend_sids:
            update_data = {
                "type": "item_update",
                "item_uuid": item_uuid,
                "item_connections": item_connections
            }
            
            logger.info(f"\n  发送数据:")
            logger.info(f"    type: {update_data['type']}")
            logger.info(f"    item_uuid: {update_data['item_uuid']}")
            logger.info(f"    item_connections: {item_connections}")
            
            for sid in backend_sids:
                try:
                    await self.sio.emit("connection_update", update_data, to=sid)
                    logger.info(f"  [OK] 已通知 Backend {sid[:16]}...")
                except Exception as e:
                    logger.error(f"  [FAIL] 通知 Backend {sid[:16]}... 失败: {e}")
            
            self._print_connection_tables(f"同步完成 - Item {item_uuid}")
            logger.info(f"{'#'*80}\n")
        else:
            logger.warning(f"  [WARN] 无已连接的Backend，跳过通知")
            logger.info(f"{'#'*80}\n")

    def get_connection_count(self) -> int:
        with self.lock:
            return sum(len(sids) for sids in self.connections.values())

    def get_terminal_count(self) -> int:
        with self.lock:
            return len(self.connections)
    
    def _print_connection_tables(self, message: str = "Connection Tables Updated"):
        logger.info(f"\n{'='*80}")
        logger.info(f"[Daemon SocketService] {message}")
        logger.info(f"{'='*80}")
        
        tables = self.get_connection_tables()
        
        logger.info("\n1. Backend连接表 [sid -> {backend_id, ip}]")
        logger.info("-" * 80)
        logger.info(f"{'SID':<36} | {'Backend ID':<20} | {'IP':<15}")
        logger.info("-" * 80)
        
        backend_count = 0
        for sid, info in tables['backend_connections'].items():
            backend_id = info.get('backend_id', 'unknown')
            ip = info.get('ip', 'unknown')
            logger.info(f"{sid[:16]}...{' '*17} | {backend_id:<20} | {ip:<15}")
            backend_count += 1
        
        if backend_count == 0:
            logger.info("  无数据")
        else:
            logger.info(f"  共 {backend_count} 个Backend连接")
        
        logger.info("\n2. Item-Token映射表 [item_uuid: token]")
        logger.info("-" * 80)
        logger.info(f"{'Item UUID':<36} | {'Token':<36}")
        logger.info("-" * 80)
        
        token_count = 0
        for item_uuid, token in tables['item_tokens'].items():
            logger.info(f"{item_uuid:<36} | {token[:16]}...")
            token_count += 1
        
        if token_count == 0:
            logger.info("  无数据")
        else:
            logger.info(f"  共 {token_count} 个Token")
        
        logger.info("\n3. Item-连接映射表 [item_uuid -> {sid -> {user_uuid, ip}}]")
        logger.info("-" * 100)
        logger.info(f"{'Item UUID':<36} | {'SID':<20} | {'User UUID':<36} | {'IP':<15}")
        logger.info("-" * 100)
        
        conn_count = 0
        for item_uuid, sids in tables['item_connections'].items():
            for sid, conn_info in sids.items():
                user_uuid = conn_info.get('user_uuid', 'unknown')
                ip = conn_info.get('ip', 'unknown')
                logger.info(f"{item_uuid:<36} | {sid[:16]}...{' '*3} | {user_uuid:<36} | {ip:<15}")
                conn_count += 1
        
        if conn_count == 0:
            logger.info("  无数据")
        else:
            logger.info(f"  共 {conn_count} 个用户连接")
        
        logger.info(f"\n{'='*80}\n")
    
    def get_item_connections(self, item_uuid: str) -> Dict[str, Any]:
        with self.lock:
            connections = {}
            if item_uuid in self.connections:
                connections = self.connections[item_uuid].copy()
            
            return {
                'item_uuid': item_uuid,
                'connections': connections
            }
    
    def get_all_connections(self) -> Dict[str, Any]:
        with self.lock:
            return self.connections.copy()
    
    def get_connection_tables(self) -> Dict[str, Any]:
        with self.lock:
            return {
                'backend_connections': self.backend_connections.copy(),
                'item_tokens': self.item_tokens.copy(),
                'item_connections': self.connections.copy()
            }
    
    async def disconnect_user_from_item(self, item_uuid: str, user_uuid: str) -> Dict[str, Any]:
        sids_to_disconnect = []
        
        with self.lock:
            if item_uuid in self.connections:
                sids_to_remove = []
                
                for sid, conn_info in self.connections[item_uuid].items():
                    if conn_info['user_uuid'] == user_uuid:
                        if conn_info['user_uuid'] == 'backend':
                            logger.warning(f"Cannot disconnect backend connection: {sid}")
                            continue
                        sids_to_disconnect.append(sid)
                        sids_to_remove.append(sid)
                
                for sid in sids_to_remove:
                    self.connections[item_uuid].pop(sid)
                    
                    if sid in self.sid_to_item:
                        self.sid_to_item.pop(sid)
                    if sid in self.sid_to_user:
                        self.sid_to_user.pop(sid)
                
                if not self.connections[item_uuid]:
                    del self.connections[item_uuid]
        
        for sid in sids_to_disconnect:
            try:
                await self.sio.disconnect(sid)
            except Exception as e:
                logger.error(f"Failed to disconnect {sid}: {e}")
        
        return self.get_terminal_connections(item_uuid)
    
    async def disconnect_by_ip(self, item_uuid: str, ip_address: str) -> Dict[str, Any]:
        sids_to_disconnect = []
        
        with self.lock:
            if item_uuid in self.connections:
                sids_to_remove = []
                
                for sid, conn_info in self.connections[item_uuid].items():
                    if conn_info['ip'] == ip_address:
                        if conn_info['user_uuid'] == 'backend':
                            logger.warning(f"Cannot disconnect backend connection: {sid}")
                            continue
                        sids_to_disconnect.append(sid)
                        sids_to_remove.append(sid)
                
                for sid in sids_to_remove:
                    self.connections[item_uuid].pop(sid)
                    
                    if sid in self.sid_to_item:
                        self.sid_to_item.pop(sid)
                    if sid in self.sid_to_user:
                        self.sid_to_user.pop(sid)
                
                if not self.connections[item_uuid]:
                    del self.connections[item_uuid]
        
        for sid in sids_to_disconnect:
            try:
                await self.sio.disconnect(sid)
            except Exception as e:
                logger.error(f"Failed to disconnect {sid}: {e}")
        
        return self.get_terminal_connections(item_uuid)
    
    def get_connections_by_ip(self, item_uuid: str, ip_address: str) -> List[Dict[str, str]]:
        result = []
        with self.lock:
            if item_uuid in self.connections:
                for sid, conn_info in self.connections[item_uuid].items():
                    if conn_info.get('ip') == ip_address:
                        result.append({
                            'sid': sid,
                            'user_uuid': conn_info.get('user_uuid'),
                            'ip': conn_info.get('ip')
                        })
        return result
    
    def get_all_connections_for_broadcast(self, item_uuid: str) -> List[Dict[str, str]]:
        result = []
        with self.lock:
            if item_uuid in self.connections:
                for sid, conn_info in self.connections[item_uuid].items():
                    result.append({
                        'sid': sid,
                        'user_uuid': conn_info.get('user_uuid'),
                        'ip': conn_info.get('ip')
                    })
        return result

    def add_backend_connection(self, item_uuid: str, sid: str, backend_id: str):
        with self.lock:
            if item_uuid not in self.connections:
                self.connections[item_uuid] = {}
            
            self.connections[item_uuid][sid] = {
                "user_uuid": "backend",
                "ip": backend_id
            }
            self.sid_to_item[sid] = item_uuid
            self.sid_to_user[sid] = "backend"
            self.sid_to_ip[sid] = backend_id
            
            memory_store.set(f"terminal_backend:{item_uuid}", backend_id)
        
        self._print_connection_tables(f"Backend Connection Added for Item {item_uuid}")
