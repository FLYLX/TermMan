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
    def __init__(self, user_uuid: str, item_uuid: str, token: str, working_directory: Optional[str] = None, command: Optional[str] = None):
        self.user_uuid = user_uuid
        self.item_uuid = item_uuid
        self.token = token
        self.process = None
        self.status = "stopped"
        self.working_directory = working_directory
        self.command = command
        self.workdir = self._get_workdir()
        self.log_path = self._get_log_path()
        self.stdout_buffer = []
        self.stderr_buffer = []
        self.lock = threading.Lock()
        self._running = True

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

    def _get_log_path(self) -> str:
        log_dir = os.path.join(
            config.get("LOG_DIR"),
            self.user_uuid
        )
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"{self.item_uuid}.log")

    def start(self) -> bool:
        try:
            self.status = "starting"
            self._running = True
            encoding = config.get("TERMINAL_ENCODING", "utf-8")
            self.encoding = encoding

            if self.command:
                self.process = subprocess.Popen(
                    self.command,
                    cwd=self.workdir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True
                )
            else:
                shell = config.get("TERMINAL_SHELL")
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

            self.status = "running"
            logger.info(f"Terminal started: {self.item_uuid}")
            return True
        except Exception as e:
            self.status = "error"
            logger.error(f"Failed to start terminal {self.item_uuid}: {e}")
            return False

    def _write_log(self, line: str, is_error: bool = False):
        try:
            from core import get_socket_service, config
            
            log_paths = set()
            connected_user_uuids = {self.user_uuid}
            
            socket_service = get_socket_service()
            if socket_service:
                try:
                    with socket_service.lock:
                        if self.item_uuid in socket_service.connections:
                            for sid, conn_info in socket_service.connections[self.item_uuid].items():
                                user_uuid = conn_info.get('user_uuid')
                                if user_uuid:
                                    connected_user_uuids.add(user_uuid)
                except Exception:
                    pass
            
            for user_uuid in connected_user_uuids:
                try:
                    user_log_dir = os.path.join(config.get("LOG_DIR"), user_uuid)
                    os.makedirs(user_log_dir, exist_ok=True)
                    log_paths.add(os.path.join(user_log_dir, f"{self.item_uuid}.log"))
                except Exception:
                    pass
            
            content = f"[ERROR] {line}" if is_error else line
            for log_path in log_paths:
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(content)
                except Exception:
                    pass
        except Exception:
            pass

    def _broadcast(self, data: dict):
        try:
            from core import get_socket_service
            socket_service = get_socket_service()
            if socket_service:
                socket_service.sync_broadcast(self.item_uuid, "stream", data)
        except Exception:
            pass

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
                
                self._write_log(decoded_line, is_error=True)
                self._broadcast({"stderr": decoded_line})
        except Exception as e:
            logger.error(f"Error reading stderr for {self.item_uuid}: {e}")

    def write(self, data: str) -> bool:
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
        try:
            self._running = False
            
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
