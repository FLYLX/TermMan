import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InputCommand:
    item_uuid: str
    command: str
    source: str = "sdk"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class InputHandler:
    handler_id: str
    item_uuid: str
    callback: Callable[[InputCommand], bool]
    handler_type: str = "generic"
    created_at: datetime = field(default_factory=datetime.now)


class InputCenter:
    """
    Item 输入中心 - 命令分发模式
    
    核心设计：
    1. 注册输入处理器（handler）来处理特定 item 的命令
    2. 通过 SDK 发送命令到指定 item
    3. 处理器将命令写入对应的终端
    
    使用场景：
    - Agent 发送命令到终端
    - 后端脚本自动化执行
    - 批量命令分发
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._handlers: dict[str, InputHandler] = {}
        self._item_handlers: dict[str, list[str]] = {}
        self._global_lock = threading.RLock()
        
        logger.info("[InputCenter] Initialized")
    
    def register(
        self,
        item_uuid: str,
        callback: Callable[[InputCommand], bool],
        handler_type: str = "generic",
        handler_id: str | None = None
    ) -> str:
        import uuid
        h_id = handler_id or f"{handler_type}_{item_uuid}_{uuid.uuid4().hex[:8]}"
        
        handler = InputHandler(
            handler_id=h_id,
            item_uuid=item_uuid,
            callback=callback,
            handler_type=handler_type
        )
        
        with self._global_lock:
            self._handlers[h_id] = handler
            
            if item_uuid not in self._item_handlers:
                self._item_handlers[item_uuid] = []
            self._item_handlers[item_uuid].append(h_id)
        
        logger.info(f"[InputCenter] Handler registered: {h_id} for item={item_uuid}")
        return h_id
    
    def unregister(self, handler_id: str) -> bool:
        with self._global_lock:
            if handler_id not in self._handlers:
                return False
            
            handler = self._handlers.pop(handler_id)
            item_uuid = handler.item_uuid
            
            if item_uuid in self._item_handlers:
                if handler_id in self._item_handlers[item_uuid]:
                    self._item_handlers[item_uuid].remove(handler_id)
                if not self._item_handlers[item_uuid]:
                    del self._item_handlers[item_uuid]
        
        logger.info(f"[InputCenter] Handler unregistered: {handler_id}")
        return True
    
    def unregister_all_by_item(self, item_uuid: str) -> int:
        count = 0
        with self._global_lock:
            if item_uuid not in self._item_handlers:
                return 0
            
            h_ids = self._item_handlers[item_uuid].copy()
            for h_id in h_ids:
                if h_id in self._handlers:
                    del self._handlers[h_id]
                    count += 1
            
            del self._item_handlers[item_uuid]
        
        logger.info(f"[InputCenter] Unregistered {count} handlers for item={item_uuid}")
        return count
    
    def send(self, item_uuid: str, command: str, source: str = "sdk") -> bool:
        input_cmd = InputCommand(
            item_uuid=item_uuid,
            command=command,
            source=source
        )
        
        with self._global_lock:
            if item_uuid not in self._item_handlers:
                logger.warning(f"[InputCenter] No handler for item={item_uuid}")
                return False
            
            h_ids = self._item_handlers[item_uuid].copy()
        
        delivered = False
        for h_id in h_ids:
            with self._global_lock:
                handler = self._handlers.get(h_id)
            
            if handler is None:
                continue
            
            try:
                if handler.callback(input_cmd):
                    delivered = True
            except Exception as e:
                logger.error(f"[InputCenter] Error in handler {h_id}: {e}")
        
        if delivered:
            logger.debug(f"[InputCenter] Command sent to item={item_uuid}: {command[:50]}...")
        
        return delivered
    
    def send_to_all(self, command: str, source: str = "sdk") -> dict[str, bool]:
        results = {}
        
        with self._global_lock:
            item_uuids = list(self._item_handlers.keys())
        
        for item_uuid in item_uuids:
            results[item_uuid] = self.send(item_uuid, command, source)
        
        return results
    
    def get_handlers_by_item(self, item_uuid: str) -> list[InputHandler]:
        with self._global_lock:
            if item_uuid not in self._item_handlers:
                return []
            return [self._handlers[hid] for hid in self._item_handlers[item_uuid] if hid in self._handlers]
    
    def get_handler_count(self, item_uuid: str | None = None) -> int:
        with self._global_lock:
            if item_uuid:
                return len(self._item_handlers.get(item_uuid, []))
            return len(self._handlers)
    
    def has_handler(self, item_uuid: str) -> bool:
        with self._global_lock:
            return item_uuid in self._item_handlers and len(self._item_handlers[item_uuid]) > 0


input_center = InputCenter()
