import os
import json
from typing import Dict, Any


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
        加载配置：默认值 < ./daemon.json < 环境变量（env 优先）。
        兼容：无 daemon.json 时回退读取当前目录 .env。
        """
        defaults = {
            "PORT": 39999,
            "HOST": "0.0.0.0",
            "API_KEY": "",
            "SECRET_KEY": "default-secret-key-change-in-production",
            "WORKDIR": "./src/workdir",
            "LOG_DIR": "./log",
            "DATA_DIR": "./src/data",
            "TERMINAL_SHELL": "cmd.exe" if os.name == "nt" else "/bin/sh",
            "TERMINAL_ENCODING": "utf-8",
            "TERMINAL_BUFFER_SIZE": 8192,
        }
        self.config_data.update(defaults)

        json_path = os.path.join(os.getcwd(), "daemon.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                self.config_data.update(json.load(f))

        env_overrides = {
            key: os.getenv(key)
            for key in defaults
            if os.getenv(key) is not None
        }
        for key in ("PORT", "TERMINAL_BUFFER_SIZE"):
            if key in env_overrides:
                env_overrides[key] = int(env_overrides[key])
        self.config_data.update(env_overrides)

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
