import os
import json
from typing import Dict, Any, Optional
import shutil


class FileStorage:
    """
    文件存储封装
    """
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_path(self, filename: str) -> str:
        """
        获取文件路径
        """
        return os.path.join(self.base_dir, filename)

    def write_json(self, filename: str, data: Any, indent: int = 2):
        """
        写入JSON文件
        """
        file_path = self._get_path(filename)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)

    def read_json(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        读取JSON文件
        """
        file_path = self._get_path(filename)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def write_file(self, filename: str, content: str):
        """
        写入文件
        """
        file_path = self._get_path(filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    def append_file(self, filename: str, content: str):
        """
        追加写入文件
        """
        file_path = self._get_path(filename)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content)

    def read_file(self, filename: str) -> Optional[str]:
        """
        读取文件
        """
        file_path = self._get_path(filename)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def exists(self, filename: str) -> bool:
        """
        检查文件是否存在
        """
        file_path = self._get_path(filename)
        return os.path.exists(file_path)

    def delete(self, filename: str) -> bool:
        """
        删除文件
        """
        file_path = self._get_path(filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                return True
            except Exception:
                return False
        return False

    def list_files(self, pattern: str = "*") -> list:
        """
        列出文件
        """
        import glob
        search_path = os.path.join(self.base_dir, pattern)
        return [os.path.basename(f) for f in glob.glob(search_path)]

    def create_directory(self, directory: str):
        """
        创建目录
        """
        dir_path = os.path.join(self.base_dir, directory)
        os.makedirs(dir_path, exist_ok=True)

    def delete_directory(self, directory: str) -> bool:
        """
        删除目录
        """
        dir_path = os.path.join(self.base_dir, directory)
        if os.path.exists(dir_path):
            try:
                shutil.rmtree(dir_path)
                return True
            except Exception:
                return False
        return False

    def get_file_size(self, filename: str) -> Optional[int]:
        """
        获取文件大小
        """
        file_path = self._get_path(filename)
        if os.path.exists(file_path):
            return os.path.getsize(file_path)
        return None

    def get_last_modified(self, filename: str) -> Optional[float]:
        """
        获取文件最后修改时间
        """
        file_path = self._get_path(filename)
        if os.path.exists(file_path):
            return os.path.getmtime(file_path)
        return None
