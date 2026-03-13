from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import threading


class MemoryItem:
    """
    内存存储项
    """
    def __init__(self, value: Any, ttl: Optional[timedelta] = None):
        self.value = value
        self.created_at = datetime.now()
        self.ttl = ttl
        self.expire_at = self.created_at + ttl if ttl else None

    def is_expired(self) -> bool:
        """
        检查是否过期
        """
        if not self.expire_at:
            return False
        return datetime.now() > self.expire_at


class MemoryStore:
    """
    内存存储核心（TTL + 内存Map）
    """
    def __init__(self):
        self.store: Dict[str, MemoryItem] = {}
        self.lock = threading.Lock()
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """
        启动清理线程
        """
        def cleanup():
            while True:
                threading.Event().wait(60)  # 每分钟清理一次
                self.cleanup_expired()

        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()

    def set(self, key: str, value: Any, ttl_minutes: Optional[int] = None):
        """
        设置存储项
        """
        ttl = timedelta(minutes=ttl_minutes) if ttl_minutes else None
        with self.lock:
            self.store[key] = MemoryItem(value, ttl)

    def get(self, key: str) -> Optional[Any]:
        """
        获取存储项
        """
        with self.lock:
            if key not in self.store:
                return None

            item = self.store[key]
            if item.is_expired():
                del self.store[key]
                return None

            return item.value

    def delete(self, key: str) -> bool:
        """
        删除存储项
        """
        with self.lock:
            if key in self.store:
                del self.store[key]
                return True
            return False

    def exists(self, key: str) -> bool:
        """
        检查键是否存在
        """
        return self.get(key) is not None

    def cleanup_expired(self):
        """
        清理过期的存储项
        """
        with self.lock:
            expired_keys = [
                key for key, item in self.store.items() if item.is_expired()
            ]
            for key in expired_keys:
                del self.store[key]

    def get_all(self) -> Dict[str, Any]:
        """
        获取所有未过期的存储项
        """
        result = {}
        with self.lock:
            for key, item in self.store.items():
                if not item.is_expired():
                    result[key] = item.value
        return result

    def clear(self):
        """
        清空所有存储项
        """
        with self.lock:
            self.store.clear()

    def count(self) -> int:
        """
        获取存储项数量
        """
        with self.lock:
            return len(self.store)
    
    def keys(self) -> list:
        """
        获取所有键列表
        """
        with self.lock:
            return list(self.store.keys())


# 创建全局内存存储实例
memory_store = MemoryStore()
