import os
import uuid
import subprocess
import threading
import chardet
from typing import Dict, Any, Optional
from core import memory_store, config
from utils.logger import logger


class TerminalProcess:
    """
    终端进程类
    """
    def __init__(self, user_uuid: str, item_uuid: str, token: str):
        self.user_uuid = user_uuid
        self.item_uuid = item_uuid
        self.token = token
        self.process = None
        self.status = "stopped"
        self.workdir = self._get_workdir()
        self.log_path = self._get_log_path()
        self.stdout_buffer = []
        self.stderr_buffer = []
        self.lock = threading.Lock()

    def _get_workdir(self) -> str:
        """
        获取终端工作目录
        """
        workdir = os.path.join(
            config.get("WORKDIR"),
            self.user_uuid,
            self.item_uuid
        )
        os.makedirs(workdir, exist_ok=True)
        return workdir

    def _get_log_path(self) -> str:
        """
        获取日志文件路径
        """
        log_dir = os.path.join(
            config.get("LOG_DIR"),
            self.user_uuid
        )
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"{self.item_uuid}.log")

    def start(self) -> bool:
        """
        启动终端进程
        """
        try:
            self.status = "starting"
            shell = config.get("TERMINAL_SHELL")
            encoding = config.get("TERMINAL_ENCODING", "utf-8")
            self.encoding = encoding

            self.process = subprocess.Popen(
                shell,
                cwd=self.workdir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )

            # 启动线程读取stdout和stderr
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()

            self.status = "running"
            logger.info(f"Terminal started: {self.item_uuid}")
            return True
        except Exception as e:
            self.status = "error"
            logger.error(f"Failed to start terminal {self.item_uuid}: {e}")
            return False

    def _read_stdout(self):
        """
        读取stdout
        """
        try:
            while self.process and self.process.stdout:
                line = self.process.stdout.readline()
                if not line:
                    break
                
                # 使用chardet自动检测编码
                try:
                    # 首先尝试使用配置的编码
                    decoded_line = line.decode(self.encoding)
                except UnicodeDecodeError:
                    # 如果失败，使用chardet检测编码
                    detected = chardet.detect(line)
                    detected_encoding = detected.get('encoding', self.encoding)
                    decoded_line = line.decode(detected_encoding, errors='replace')
                
                with self.lock:
                    self.stdout_buffer.append(decoded_line)
                    
                    # 为所有连接的用户写入各自的日志文件
                    try:
                        import sys
                        import os
                        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        from core import get_socket_service
                        socket_service = get_socket_service()
                        
                        # 收集所有需要写入的日志路径
                        log_paths = set()
                        
                        # 添加主日志路径（创建终端的用户）
                        log_paths.add(self.log_path)
                        
                        # 如果有其他连接的用户，添加他们的日志路径
                        if socket_service:
                            # 获取所有连接的用户
                            with socket_service.lock:
                                if self.item_uuid in socket_service.connections:
                                    for conn in socket_service.connections[self.item_uuid]:
                                        user_uuid = conn['user_uuid']
                                        # 为每个用户创建日志文件
                                        user_log_dir = os.path.join(
                                            config.get("LOG_DIR"),
                                            user_uuid
                                        )
                                        os.makedirs(user_log_dir, exist_ok=True)
                                        user_log_path = os.path.join(user_log_dir, f"{self.item_uuid}.log")
                                        log_paths.add(user_log_path)
                        
                        # 写入所有唯一的日志路径
                        for log_path in log_paths:
                            with open(log_path, "a", encoding="utf-8") as f:
                                f.write(decoded_line)
                    except Exception as e:
                        logger.error(f"Error writing user logs for {self.item_uuid}: {e}")
                
                # 转发到Socket.IO
                try:
                    import sys
                    import os
                    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from core import get_socket_service
                    import asyncio
                    socket_service = get_socket_service()
                    if socket_service:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            socket_service.broadcast_to_terminal(
                                self.item_uuid, "stream", {"stdout": decoded_line}
                            )
                        )
                        loop.close()
                except Exception as e:
                    logger.error(f"Error broadcasting stdout to socket: {e}")
        except Exception as e:
            logger.error(f"Error reading stdout for {self.item_uuid}: {e}")

    def _read_stderr(self):
        """
        读取stderr
        """
        try:
            while self.process and self.process.stderr:
                line = self.process.stderr.readline()
                if not line:
                    break
                
                # 使用chardet自动检测编码
                try:
                    # 首先尝试使用配置的编码
                    decoded_line = line.decode(self.encoding)
                except UnicodeDecodeError:
                    # 如果失败，使用chardet检测编码
                    detected = chardet.detect(line)
                    detected_encoding = detected.get('encoding', self.encoding)
                    decoded_line = line.decode(detected_encoding, errors='replace')
                
                with self.lock:
                    self.stderr_buffer.append(decoded_line)
                    
                    # 为所有连接的用户写入各自的日志文件
                    try:
                        import sys
                        import os
                        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        from core import get_socket_service
                        socket_service = get_socket_service()
                        
                        # 收集所有需要写入的日志路径
                        log_paths = set()
                        
                        # 添加主日志路径（创建终端的用户）
                        log_paths.add(self.log_path)
                        
                        # 如果有其他连接的用户，添加他们的日志路径
                        if socket_service:
                            # 获取所有连接的用户
                            with socket_service.lock:
                                if self.item_uuid in socket_service.connections:
                                    for conn in socket_service.connections[self.item_uuid]:
                                        user_uuid = conn['user_uuid']
                                        # 为每个用户创建日志文件
                                        user_log_dir = os.path.join(
                                            config.get("LOG_DIR"),
                                            user_uuid
                                        )
                                        os.makedirs(user_log_dir, exist_ok=True)
                                        user_log_path = os.path.join(user_log_dir, f"{self.item_uuid}.log")
                                        log_paths.add(user_log_path)
                        
                        # 写入所有唯一的日志路径
                        error_line = f"[ERROR] {decoded_line}"
                        for log_path in log_paths:
                            with open(log_path, "a", encoding="utf-8") as f:
                                f.write(error_line)
                    except Exception as e:
                        logger.error(f"Error writing user logs for {self.item_uuid}: {e}")
                
                # 转发到Socket.IO
                try:
                    import sys
                    import os
                    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from core import get_socket_service
                    import asyncio
                    socket_service = get_socket_service()
                    if socket_service:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            socket_service.broadcast_to_terminal(
                                self.item_uuid, "stream", {"stderr": decoded_line}
                            )
                        )
                        loop.close()
                except Exception as e:
                    logger.error(f"Error broadcasting stderr to socket: {e}")
        except Exception as e:
            logger.error(f"Error reading stderr for {self.item_uuid}: {e}")

    def write(self, data: str) -> bool:
        """
        向终端写入数据
        """
        try:
            if self.process and self.process.stdin and self.status == "running":
                if isinstance(data, str):
                    data = data.encode(self.encoding)
                self.process.stdin.write(data)
                self.process.stdin.flush()
                return True
            return False
        except Exception as e:
            logger.error(f"Error writing to terminal {self.item_uuid}: {e}")
            return False

    def stop(self) -> bool:
        """
        停止终端进程
        """
        try:
            if self.process:
                self.process.terminate()
                self.process.wait(timeout=5)
                self.process = None
            self.status = "stopped"
            logger.info(f"Terminal stopped: {self.item_uuid}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop terminal {self.item_uuid}: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """
        获取终端状态
        """
        with self.lock:
            stdout = "".join(self.stdout_buffer)
            stderr = "".join(self.stderr_buffer)
            self.stdout_buffer = []
            self.stderr_buffer = []

        return {
            "item_uuid": self.item_uuid,
            "user_uuid": self.user_uuid,
            "status": self.status,
            "workdir": self.workdir,
            "log_path": self.log_path,
            "stdout": stdout,
            "stderr": stderr
        }


class TerminalManager:
    """
    终端进程管理类
    """
    def __init__(self):
        self.terminals: Dict[str, TerminalProcess] = {}
        self.lock = threading.Lock()

    def create_terminal(self, user_uuid: str, token: str) -> str:
        """
        创建新终端
        """
        item_uuid = str(uuid.uuid4())
        with self.lock:
            terminal = TerminalProcess(user_uuid, item_uuid, token)
            self.terminals[item_uuid] = terminal
        return item_uuid

    def get_terminal(self, item_uuid: str) -> Optional[TerminalProcess]:
        """
        获取终端
        """
        with self.lock:
            return self.terminals.get(item_uuid)

    def start_terminal(self, item_uuid: str) -> bool:
        """
        启动终端
        """
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return False
        return terminal.start()

    def stop_terminal(self, item_uuid: str) -> bool:
        """
        停止终端
        """
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return False
        result = terminal.stop()
        if result:
            with self.lock:
                if item_uuid in self.terminals:
                    del self.terminals[item_uuid]
        return result

    def write_to_terminal(self, item_uuid: str, data: str) -> bool:
        """
        向终端写入数据
        """
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return False
        return terminal.write(data)

    def get_terminal_status(self, item_uuid: str) -> Optional[Dict[str, Any]]:
        """
        获取终端状态
        """
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return None
        return terminal.get_status()

    def get_user_terminals(self, user_uuid: str) -> list:
        """
        获取用户的所有终端
        """
        with self.lock:
            return [
                terminal.get_status()
                for terminal in self.terminals.values()
                if terminal.user_uuid == user_uuid
            ]

    def get_all_terminals(self) -> list:
        """
        获取所有终端
        """
        with self.lock:
            return [terminal.get_status() for terminal in self.terminals.values()]


# 创建全局终端管理器实例
terminal_manager = TerminalManager()
