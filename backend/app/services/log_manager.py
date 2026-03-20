import os
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any

DEFAULT_MAX_LOG_SIZE = 3 * 1024 * 1024
LOG_DIR = "log"


class LogManager:
    """
    日志管理器，用于保存终端输出到文件
    
    日志路径: log/{item_uuid}.log
    """
    def __init__(self, base_dir: str = None, max_log_size: int = None):
        self.base_dir = base_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_DIR)
        self.max_log_size = max_log_size or DEFAULT_MAX_LOG_SIZE
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        
        os.makedirs(self.base_dir, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.info(f"[LogManager] Initialized with base_dir: {self.base_dir}")
    
    def _get_lock(self, item_uuid: str) -> threading.Lock:
        with self._global_lock:
            if item_uuid not in self._locks:
                self._locks[item_uuid] = threading.Lock()
            return self._locks[item_uuid]
        
    def get_log_path(self, item_uuid: str) -> str:
        """
        获取日志文件路径
        
        Args:
            item_uuid: 终端UUID
            
        Returns:
            日志文件的绝对路径: log/{item_uuid}.log
        """
        return os.path.join(self.base_dir, f"{item_uuid}.log")
    
    def write_to_log(self, user_uuid: str, item_uuid: str, content: str) -> bool:
        """
        写入日志到文件
        
        Args:
            user_uuid: 用户UUID (保留参数兼容性)
            item_uuid: 终端UUID
            content: 要写入的内容
            
        Returns:
            是否成功写入
        """
        lock = self._get_lock(item_uuid)
        with lock:
            try:
                log_path = self.get_log_path(item_uuid)
                self.logger.info(f"[LogManager] Writing to log: {log_path}, content length: {len(content)}")
                
                if os.path.exists(log_path):
                    file_size = os.path.getsize(log_path)
                    if file_size >= self.max_log_size:
                        with open(log_path, "w", encoding="utf-8") as f:
                            f.write("""=== 日志文件已超出最大大小，已清空 ===\n\n""")
                
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(content)
                
                return True
            except Exception as e:
                self.logger.error(f"Failed to write log for terminal {item_uuid}: {e}")
                return False
    
    def get_log_content(self, user_uuid: str, item_uuid: str) -> Optional[str]:
        """
        获取日志文件内容
        
        Args:
            user_uuid: 用户UUID (保留参数兼容性)
            item_uuid: 终端UUID
            
        Returns:
            日志文件内容，如果文件不存在返回None
        """
        try:
            log_path = self.get_log_path(item_uuid)
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    return f.read()
            return None
        except Exception as e:
            self.logger.error(f"Failed to read log for terminal {item_uuid}: {e}")
            return None
    
    def get_last_lines(self, item_uuid: str, lines: int = 64) -> Optional[str]:
        """
        获取日志文件最后N行内容
        
        Args:
            item_uuid: 终端UUID
            lines: 要获取的行数，默认64行
            
        Returns:
            最后N行日志内容，如果文件不存在返回None
        """
        try:
            log_path = self.get_log_path(item_uuid)
            if not os.path.exists(log_path):
                return None
            
            with open(log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return "".join(last_lines)
        except Exception as e:
            self.logger.error(f"Failed to read last {lines} lines for terminal {item_uuid}: {e}")
            return None
    
    def delete_log(self, user_uuid: str, item_uuid: str) -> bool:
        """
        删除日志文件
        
        Args:
            user_uuid: 用户UUID (保留参数兼容性)
            item_uuid: 终端UUID
            
        Returns:
            是否成功删除
        """
        try:
            log_path = self.get_log_path(item_uuid)
            if os.path.exists(log_path):
                os.remove(log_path)
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete log for terminal {item_uuid}: {e}")
            return False
    
    def set_max_log_size(self, max_size: int) -> None:
        self.max_log_size = max_size
    
    def get_max_log_size(self) -> int:
        return self.max_log_size
