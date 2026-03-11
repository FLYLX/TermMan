import os
import logging
from logging.handlers import TimedRotatingFileHandler
from core import config


class Logger:
    """
    日志写入工具类
    """
    def __init__(self):
        self.logger = logging.getLogger("termman-daemon")
        self.logger.setLevel(logging.INFO)
        self._setup_handlers()

    def _setup_handlers(self):
        """
        设置日志处理器
        """
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        # 文件处理器
        log_dir = config.get("LOG_DIR")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "daemon.log")
        
        file_handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=7
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

    def debug(self, message):
        """
        写入调试日志
        """
        self.logger.debug(message)

    def info(self, message):
        """
        写入信息日志
        """
        self.logger.info(message)

    def warning(self, message):
        """
        写入警告日志
        """
        self.logger.warning(message)

    def error(self, message):
        """
        写入错误日志
        """
        self.logger.error(message)

    def critical(self, message):
        """
        写入严重错误日志
        """
        self.logger.critical(message)


# 创建全局日志实例
logger = Logger()
