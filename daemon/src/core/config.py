import os
import json
from typing import Dict, Any
from dotenv import load_dotenv


class Config:
    """
    配置管理类
    """
    def __init__(self):
        self.config_data = {}
        self.load_env()
        self.load_config_file()

    def load_env(self):
        """
        加载环境变量
        """
        load_dotenv()
        self.config_data.update({
            "PORT": int(os.getenv("PORT", "9000")),
            "HOST": os.getenv("HOST", "0.0.0.0"),
            "API_KEY": os.getenv("API_KEY", ""),
            "SECRET_KEY": os.getenv("SECRET_KEY", "default-secret-key-change-in-production"),
            "WORKDIR": os.getenv("WORKDIR", "./src/workdir"),
            "LOG_DIR": os.getenv("LOG_DIR", "./log"),
            "DATA_DIR": os.getenv("DATA_DIR", "./src/data"),
            "TERMINAL_SHELL": os.getenv("TERMINAL_SHELL", "cmd.exe"),
            "TERMINAL_ENCODING": os.getenv("TERMINAL_ENCODING", "utf-8"),
            "TERMINAL_BUFFER_SIZE": int(os.getenv("TERMINAL_BUFFER_SIZE", "8192")),
            "BACKEND_URL": os.getenv("BACKEND_URL", "http://backend:8000")
        })

    def load_config_file(self):
        """
        加载配置文件
        """
        config_path = os.path.join(self.config_data["DATA_DIR"], "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                self.config_data.update(file_config)

    def save_config_file(self):
        """
        保存配置到文件
        """
        config_path = os.path.join(self.config_data["DATA_DIR"], "config.json")
        # 只保存非敏感配置
        save_config = {
            key: value for key, value in self.config_data.items()
            if key not in ["API_KEY"]
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(save_config, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        """
        return self.config_data.get(key, default)

    def set(self, key: str, value: Any):
        """
        设置配置值
        """
        self.config_data[key] = value

    def get_all(self) -> Dict[str, Any]:
        """
        获取所有配置
        """
        return self.config_data.copy()

    def ensure_directories(self):
        """
        确保必要的目录存在
        """
        directories = [
            self.config_data["WORKDIR"],
            self.config_data["LOG_DIR"],
            os.path.join(self.config_data["DATA_DIR"], "terminals"),
            os.path.join(self.config_data["DATA_DIR"], "logs")
        ]
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)


# 创建全局配置实例
config = Config()
config.ensure_directories()
