import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class ItemHandlerContext:
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
        
        self._item_handlers: dict[str, str] = {}
        self._global_lock = threading.RLock()
        
        logger.info("[ItemHandlerContext] Initialized")
    
    def set_handler(self, item_id: str, handler_id: str):
        with self._global_lock:
            self._item_handlers[item_id] = handler_id
            logger.info(f"[ItemHandlerContext] Set handler={handler_id} for item={item_id}")
    
    def get_handler(self, item_id: str) -> Optional[str]:
        with self._global_lock:
            return self._item_handlers.get(item_id)
    
    def remove_handler(self, item_id: str):
        with self._global_lock:
            if item_id in self._item_handlers:
                del self._item_handlers[item_id]
                logger.info(f"[ItemHandlerContext] Removed handler for item={item_id}")


item_handler_context = ItemHandlerContext()
