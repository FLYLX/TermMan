import os
import pty
import struct
import fcntl
import termios
import threading
import chardet
import signal
from typing import Dict, Any, Optional
from datetime import datetime
from core import config
from utils.logger import logger


class DaemonLogManager:
    """
    Daemon 本地日志管理器
    
    日志路径: daemon/log/{item_uuid}.log
    """
    def __init__(self, base_dir: str = None, max_log_size: int = None):
        if base_dir is None:
            current_file = os.path.abspath(__file__)
            daemon_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
            self.base_dir = os.path.join(daemon_dir, "log")
        else:
            self.base_dir = base_dir
        self.max_log_size = max_log_size or (3 * 1024 * 1024)
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        os.makedirs(self.base_dir, exist_ok=True)
    
    def _get_lock(self, item_uuid: str) -> threading.Lock:
        with self._global_lock:
            if item_uuid not in self._locks:
                self._locks[item_uuid] = threading.Lock()
            return self._locks[item_uuid]

    def get_log_path(self, item_uuid: str) -> str:
        return os.path.join(self.base_dir, f"{item_uuid}.log")

    def write_to_log(self, item_uuid: str, content: str) -> bool:
        lock = self._get_lock(item_uuid)
        with lock:
            try:
                log_path = self.get_log_path(item_uuid)
                
                if os.path.exists(log_path):
                    file_size = os.path.getsize(log_path)
                    if file_size >= self.max_log_size:
                        with open(log_path, "w", encoding="utf-8") as f:
                            f.write("=== 日志文件已超出最大大小，已清空 ===\n\n")
                
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(content)
                
                return True
            except Exception as e:
                logger.error(f"Failed to write log for terminal {item_uuid}: {e}")
                return False

    def delete_log(self, item_uuid: str) -> bool:
        try:
            log_path = self.get_log_path(item_uuid)
            if os.path.exists(log_path):
                os.remove(log_path)
            return True
        except Exception as e:
            logger.error(f"Failed to delete log for terminal {item_uuid}: {e}")
            return False


daemon_log_manager = DaemonLogManager()


class TerminalProcess:
    """
    终端进程类 - 使用 PTY 伪终端
    
    优势：
    1. 完全模拟真实终端行为
    2. 支持 Python 交互模式（>>> 提示符）
    3. 实时回显
    4. 正确处理颜色和特殊字符
    """
    def __init__(self, user_uuid: str, item_uuid: str, token: str, working_directory: Optional[str] = None, command: Optional[str] = None):
        self.user_uuid = user_uuid
        self.item_uuid = item_uuid
        self.token = token
        self.pid = None
        self.master_fd = None
        self.status = "stopped"
        self.working_directory = working_directory
        self.command = command
        self.workdir = self._get_workdir()
        self.stdout_buffer = []
        self.lock = threading.Lock()
        self._running = True
        self._backend_connected = threading.Event()
        self._backend_connected_timeout = 30
        self.encoding = "utf-8"
        self._rows = 24
        self._cols = 80
        self._line_buffer = ""

    def _get_workdir(self) -> str:
        if self.working_directory:
            workdir = self.working_directory
        else:
            workdir = os.path.join(
                config.get("WORKDIR"),
                self.user_uuid,
                self.item_uuid
            )
        os.makedirs(workdir, exist_ok=True)
        return workdir

    def notify_backend_connected(self):
        logger.info(f"[Terminal] Backend connected for item={self.item_uuid}")
        self._backend_connected.set()

    def set_terminal_size(self, rows: int, cols: int):
        self._rows = rows
        self._cols = cols
        if self.master_fd is not None:
            try:
                winsize = struct.pack('HHHH', rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception as e:
                logger.error(f"Failed to set terminal size: {e}")

    def start(self) -> bool:
        try:
            self.status = "starting"
            self._running = True
            self.encoding = config.get("TERMINAL_ENCODING", "utf-8")
            
            shell = config.get("TERMINAL_SHELL", "/bin/bash")
            
            pid, master_fd = pty.fork()
            
            if pid == 0:
                os.chdir(self.workdir)
                
                os.environ['TERM'] = 'xterm-256color'
                os.environ['COLUMNS'] = str(self._cols)
                os.environ['LINES'] = str(self._rows)
                
                os.execvp(shell, [shell])
            else:
                self.pid = pid
                self.master_fd = master_fd
                
                flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
                fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                
                self.set_terminal_size(self._rows, self._cols)
                
                threading.Thread(target=self._read_output, daemon=True).start()
                
                self.status = "waiting_backend"
                logger.info(f"[Terminal] PTY started (pid={pid}), waiting for Backend connection: {self.item_uuid}")
                
                self._write_log(f"\n{'='*60}\n")
                self._write_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Terminal started (PTY mode)\n")
                self._write_log(f"  Item UUID: {self.item_uuid}\n")
                self._write_log(f"  User UUID: {self.user_uuid}\n")
                self._write_log(f"  Working Directory: {self.workdir}\n")
                self._write_log(f"  Command: {self.command or '(interactive shell)'}\n")
                self._write_log(f"{'='*60}\n\n")
                
                def wait_and_execute():
                    if self._backend_connected.wait(timeout=self._backend_connected_timeout):
                        logger.info(f"[Terminal] Backend connected, executing commands for item={self.item_uuid}")
                        self.status = "running"
                        
                        if self.command:
                            cmd = f"{self.command}\n"
                            self.write(cmd)
                    else:
                        logger.warning(f"[Terminal] Backend connection timeout, proceeding anyway for item={self.item_uuid}")
                        self.status = "running"
                        
                        if self.command:
                            cmd = f"{self.command}\n"
                            self.write(cmd)
                
                threading.Thread(target=wait_and_execute, daemon=True).start()
                
                return True
        except Exception as e:
            self.status = "error"
            logger.error(f"Failed to start terminal {self.item_uuid}: {e}")
            return False

    def _write_log(self, content: str):
        daemon_log_manager.write_to_log(self.item_uuid, content)

    def _broadcast(self, data: dict):
        try:
            from core import get_socket_service
            socket_service = get_socket_service()
            if socket_service:
                socket_service.sync_broadcast(self.item_uuid, "stream", data)
        except Exception as e:
            logger.error(f"[TerminalProcess] Broadcast failed: {e}")

    def _read_output(self):
        while self._running and self.master_fd is not None:
            try:
                data = os.read(self.master_fd, 4096)
                if not data:
                    logger.info(f"[Terminal] PTY master closed for {self.item_uuid}")
                    break
                
                try:
                    decoded = data.decode(self.encoding)
                except UnicodeDecodeError:
                    try:
                        detected = chardet.detect(data)
                        detected_encoding = detected.get('encoding', self.encoding)
                        decoded = data.decode(detected_encoding, errors='replace')
                    except Exception:
                        decoded = data.decode(self.encoding, errors='replace')
                
                with self.lock:
                    self.stdout_buffer.append(decoded)
                
                if '\r' in decoded and '\n' not in decoded:
                    self._broadcast({"stdout": decoded})
                    continue
                
                self._line_buffer += decoded
                self._line_buffer = self._line_buffer.replace('\r\n', '\n').replace('\r', '')
                lines = self._line_buffer.split('\n')
                self._line_buffer = lines[-1]
                
                for line in lines[:-1]:
                    if line.strip():
                        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
                        timestamped_line = f"{timestamp} {line}\n"
                        self._write_log(timestamped_line)
                        self._broadcast({"stdout": timestamped_line})
                
            except BlockingIOError:
                import time
                time.sleep(0.01)
            except OSError:
                break
            except Exception as e:
                logger.error(f"Error reading output for {self.item_uuid}: {e}")
                break
        
        self._running = False
        self.status = "stopped"

    def write(self, data: str) -> bool:
        try:
            if self.master_fd is not None and self.status in ["running", "waiting_backend"]:
                if isinstance(data, str):
                    encoded_data = data.encode(self.encoding)
                else:
                    encoded_data = data
                
                os.write(self.master_fd, encoded_data)
                return True
            return False
        except Exception as e:
            logger.error(f"Error writing to terminal {self.item_uuid}: {e}")
            return False

    def stop(self) -> bool:
        try:
            self._running = False
            
            self._write_log(f"\n\n{'='*60}\n")
            self._write_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Terminal stopped\n")
            self._write_log(f"{'='*60}\n")
            
            if self.pid is not None:
                try:
                    os.kill(self.pid, signal.SIGTERM)
                    import time
                    time.sleep(0.1)
                    try:
                        os.kill(self.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                except ProcessLookupError:
                    pass
                self.pid = None
            
            if self.master_fd is not None:
                try:
                    os.close(self.master_fd)
                except Exception:
                    pass
                self.master_fd = None
            
            self.status = "stopped"
            logger.info(f"Terminal stopped: {self.item_uuid}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop terminal {self.item_uuid}: {e}")
            self.status = "stopped"
            self.pid = None
            self.master_fd = None
            return True

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            stdout = "".join(self.stdout_buffer)
            self.stdout_buffer = []

        return {
            "item_uuid": self.item_uuid,
            "user_uuid": self.user_uuid,
            "status": self.status,
            "workdir": self.workdir,
            "stdout": stdout
        }


class TerminalManager:
    """
    终端进程管理类
    """
    def __init__(self):
        self.terminals: Dict[str, TerminalProcess] = {}
        self.lock = threading.Lock()

    def create_terminal(self, user_uuid: str, token: str, working_directory: Optional[str] = None, command: Optional[str] = None, item_uuid: Optional[str] = None) -> str:
        if not item_uuid:
            raise ValueError("Missing item_uuid")
        with self.lock:
            terminal = TerminalProcess(user_uuid, item_uuid, token, working_directory, command)
            self.terminals[item_uuid] = terminal
        return item_uuid

    def get_terminal(self, item_uuid: str) -> Optional[TerminalProcess]:
        with self.lock:
            return self.terminals.get(item_uuid)

    def start_terminal(self, item_uuid: str) -> bool:
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return False
        return terminal.start()

    def notify_backend_connected(self, item_uuid: str):
        """通知指定终端 Backend 已连接"""
        terminal = self.get_terminal(item_uuid)
        if terminal:
            terminal.notify_backend_connected()

    def stop_terminal(self, item_uuid: str) -> bool:
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return True
        
        terminal.stop()
        
        with self.lock:
            if item_uuid in self.terminals:
                del self.terminals[item_uuid]
        
        return True

    def write_to_terminal(self, item_uuid: str, data: str) -> bool:
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return False
        return terminal.write(data)

    def get_terminal_status(self, item_uuid: str) -> Optional[Dict[str, Any]]:
        terminal = self.get_terminal(item_uuid)
        if not terminal:
            return None
        return terminal.get_status()

    def get_user_terminals(self, user_uuid: str) -> list:
        with self.lock:
            return [
                terminal.get_status()
                for terminal in self.terminals.values()
                if terminal.user_uuid == user_uuid
            ]

    def get_all_terminals(self) -> list:
        with self.lock:
            return [terminal.get_status() for terminal in self.terminals.values()]


terminal_manager = TerminalManager()
