import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any

# 默认配置
DEFAULT_MAX_LOG_SIZE = 3 * 1024 * 1024  # 3MB
LOG_DIR = "log"

class LogManager:
    """
    日志管理器，用于保存终端输出到文件
    """
    def __init__(self, base_dir: str = None, max_log_size: int = None):
        """
        初始化日志管理器
        
        Args:
            base_dir: 日志文件的基础目录，默认使用当前目录下的log目录
            max_log_size: 最大日志文件大小，默认3MB
        """
        self.base_dir = base_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_DIR)
        self.max_log_size = max_log_size or DEFAULT_MAX_LOG_SIZE
        
        # 创建基础目录
        os.makedirs(self.base_dir, exist_ok=True)
        
        # 设置日志配置
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
    def get_log_path(self, user_uuid: str, item_uuid: str) -> str:
        """
        获取日志文件路径
        
        Args:
            user_uuid: 用户UUID
            item_uuid: 终端UUID
            
        Returns:
            日志文件的绝对路径
        """
        user_dir = os.path.join(self.base_dir, user_uuid)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, f"{item_uuid}.log")
    
    def write_to_log(self, user_uuid: str, item_uuid: str, content: str) -> bool:
        """
        写入日志到文件
        
        Args:
            user_uuid: 用户UUID
            item_uuid: 终端UUID
            content: 要写入的内容
            
        Returns:
            是否成功写入
        """
        try:
            log_path = self.get_log_path(user_uuid, item_uuid)
            
            # 检查日志文件大小
            if os.path.exists(log_path):
                file_size = os.path.getsize(log_path)
                if file_size >= self.max_log_size:
                    # 如果超过最大大小，清空文件
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write("""=== 日志文件已超出最大大小，已清空 ===\n\n""")
            
            # 写入内容
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(content)
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to write log for user {user_uuid} and terminal {item_uuid}: {e}")
            return False
    
    def get_log_content(self, user_uuid: str, item_uuid: str) -> Optional[str]:
        """
        获取日志文件内容
        
        Args:
            user_uuid: 用户UUID
            item_uuid: 终端UUID
            
        Returns:
            日志文件内容，如果文件不存在返回None
        """
        try:
            log_path = self.get_log_path(user_uuid, item_uuid)
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    return f.read()
            return None
        except Exception as e:
            self.logger.error(f"Failed to read log for user {user_uuid} and terminal {item_uuid}: {e}")
            return None
    
    def delete_log(self, user_uuid: str, item_uuid: str) -> bool:
        """
        删除日志文件
        
        Args:
            user_uuid: 用户UUID
            item_uuid: 终端UUID
            
        Returns:
            是否成功删除
        """
        try:
            log_path = self.get_log_path(user_uuid, item_uuid)
            if os.path.exists(log_path):
                os.remove(log_path)
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete log for user {user_uuid} and terminal {item_uuid}: {e}")
            return False
    
    def set_max_log_size(self, max_size: int) -> None:
        """
        设置最大日志文件大小
        
        Args:
            max_size: 最大日志文件大小，单位字节
        """
        self.max_log_size = max_size
    
    def get_max_log_size(self) -> int:
        """
        获取最大日志文件大小
        
        Returns:
            最大日志文件大小，单位字节
        """
        return self.max_log_size
