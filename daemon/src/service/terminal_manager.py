import os
import uuid
import subprocess
import threading
import chardet
import time
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
        os.makedirs(self.base_dir, exist_ok=True)

    def get_log_path(self, item_uuid: str) -> str:
        return os.path.join(self.base_dir, f"{item_uuid}.log")

    def write_to_log(self, item_uuid: str, content: str) -> bool:
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
    终端进程类 - 按 UPDATE.MD 规范
    
    启动流程：
    1. 先启动 shell
    2. 等待 Backend 日志 socket 连接进入 room
    3. 执行 cd workdir
    4. 执行 command
    5. 广播输出到 Room，同时写入本地日志
    """
    def __init__(self, user_uuid: str, item_uuid: str, token: str, working_directory: Optional[str] = None, command: Optional[str] = None):
        self.user_uuid = user_uuid
        self.item_uuid = item_uuid
        self.token = token
        self.process = None
        self.status = "stopped"
        self.working_directory = working_directory
        self.command = command
        self.workdir = self._get_workdir()
        self.stdout_buffer = []
        self.stderr_buffer = []
        self.lock = threading.Lock()
        self._running = True
        self._backend_connected = threading.Event()
        self._backend_connected_timeout = 30
        self.encoding = "utf-8"

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
        """通知 Backend 日志 socket 已连接"""
        logger.info(f"[Terminal] Backend connected for item={self.item_uuid}")
        self._backend_connected.set()

    def start(self) -> bool:
        try:
            self.status = "starting"
            self._running = True
            self.encoding = config.get("TERMINAL_ENCODING", "utf-8")

            shell = config.get("TERMINAL_SHELL", "/bin/bash")
            
            self.process = subprocess.Popen(
                shell,
                cwd=self.workdir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )

            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()

            self.status = "waiting_backend"
            logger.info(f"[Terminal] Shell started, waiting for Backend connection: {self.item_uuid}")

            self._write_log(f"\n{'='*60}\n")
            self._write_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Terminal started\n")
            self._write_log(f"  Item UUID: {self.item_uuid}\n")
            self._write_log(f"  User UUID: {self.user_uuid}\n")
            self._write_log(f"  Working Directory: {self.workdir}\n")
            self._write_log(f"  Command: {self.command or '(interactive shell)'}\n")
            self._write_log(f"{'='*60}\n\n")

            def wait_and_execute():
                if self._backend_connected.wait(timeout=self._backend_connected_timeout):
                    logger.info(f"[Terminal] Backend connected, executing commands for item={self.item_uuid}")
                    self.status = "running"
                    
                    time.sleep(0.3)
                    
                    if self.working_directory:
                        cd_cmd = f"cd {self.working_directory}\n"
                        self.write(cd_cmd)
                        self._write_log(f"$ {cd_cmd}")
                        time.sleep(0.1)
                    
                    if self.command:
                        cmd = f"{self.command}\n"
                        self.write(cmd)
                        self._write_log(f"$ {self.command}\n")
                else:
                    logger.warning(f"[Terminal] Backend connection timeout, proceeding anyway for item={self.item_uuid}")
                    self.status = "running"
                    
                    if self.working_directory:
                        cd_cmd = f"cd {self.working_directory}\n"
                        self.write(cd_cmd)
                    
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
        """写入本地日志"""
        daemon_log_manager.write_to_log(self.item_uuid, content)

    def _broadcast(self, data: dict):
        try:
            from core import get_socket_service
            socket_service = get_socket_service()
            if socket_service:
                logger.info(f"[TerminalProcess] Broadcasting to room {self.item_uuid}: {str(data)[:100]}...")
                socket_service.sync_broadcast(self.item_uuid, "stream", data)
                logger.info(f"[TerminalProcess] Broadcast completed")
            else:
                logger.error(f"[TerminalProcess] socket_service is None!")
        except Exception as e:
            logger.error(f"[TerminalProcess] Broadcast failed: {e}")

    def _read_stdout(self):
        try:
            while self._running and self.process and self.process.stdout:
                try:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                except Exception:
                    break
                
                try:
                    decoded_line = line.decode(self.encoding)
                except UnicodeDecodeError:
                    try:
                        detected = chardet.detect(line)
                        detected_encoding = detected.get('encoding', self.encoding)
                        decoded_line = line.decode(detected_encoding, errors='replace')
                    except Exception:
                        decoded_line = line.decode(self.encoding, errors='replace')
                
                with self.lock:
                    self.stdout_buffer.append(decoded_line)
                
                self._write_log(decoded_line)
                self._broadcast({"stdout": decoded_line})
        except Exception as e:
            logger.error(f"Error reading stdout for {self.item_uuid}: {e}")

    def _read_stderr(self):
        try:
            while self._running and self.process and self.process.stderr:
                try:
                    line = self.process.stderr.readline()
                    if not line:
                        break
                except Exception:
                    break
                
                try:
                    decoded_line = line.decode(self.encoding)
                except UnicodeDecodeError:
                    try:
                        detected = chardet.detect(line)
                        detected_encoding = detected.get('encoding', self.encoding)
                        decoded_line = line.decode(detected_encoding, errors='replace')
                    except Exception:
                        decoded_line = line.decode(self.encoding, errors='replace')
                
                with self.lock:
                    self.stderr_buffer.append(decoded_line)
                
                self._write_log(decoded_line)
                self._broadcast({"stderr": decoded_line})
        except Exception as e:
            logger.error(f"Error reading stderr for {self.item_uuid}: {e}")

    def write(self, data: str) -> bool:
        try:
            if self.process and self.process.stdin and self.status in ["running", "waiting_backend"]:
                if isinstance(data, str):
                    encoded_data = data.encode(self.encoding)
                else:
                    encoded_data = data
                
                self.process.stdin.write(encoded_data)
                self.process.stdin.flush()
                
                if isinstance(data, str) and data.strip():
                    self._write_log(f"$ {data.strip()}\n")
                    self._broadcast({"stdin": data})
                
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
            
            if self.process:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass
                
                self.process.terminate()
                
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                
                try:
                    self.process.stdout.close()
                except Exception:
                    pass
                try:
                    self.process.stderr.close()
                except Exception:
                    pass
                
                self.process = None
                
            self.status = "stopped"
            logger.info(f"Terminal stopped: {self.item_uuid}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop terminal {self.item_uuid}: {e}")
            self.status = "stopped"
            self.process = None
            return True

    def get_status(self) -> Dict[str, Any]:
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
