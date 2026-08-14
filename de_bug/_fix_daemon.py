import re

f = r"E:\dev\TermPaws\dev\TermPaws\daemon\src\service\terminal_manager.py"
with open(f, "r", encoding="utf-8") as fh:
    content = fh.read()

# === FIX 1: Add deque import ===
content = content.replace(
    "from typing import Dict, Any, Optional",
    "from collections import deque\nfrom typing import Dict, Any, Optional"
)

# === FIX 2: stdout_buffer -> deque with maxlen ===
content = content.replace(
    "        self.stdout_buffer = []",
    "        self.stdout_buffer = deque(maxlen=2000)"
)

# === FIX 3: DaemonLogManager - persistent file handles ===
old_log_manager = '''class DaemonLogManager:
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
                            f.write("=== 日志文件已超出最大大小，已清空 ===\\n\\n")
                
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
            return False'''

new_log_manager = '''class DaemonLogManager:
    """
    Daemon 本地日志管理器（持久文件句柄版）
    
    日志路径: daemon/log/{item_uuid}.log
    """
    ROTATION_CHECK_INTERVAL = 50

    def __init__(self, base_dir: str = None, max_log_size: int = None):
        if base_dir is None:
            current_file = os.path.abspath(__file__)
            daemon_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
            self.base_dir = os.path.join(daemon_dir, "log")
        else:
            self.base_dir = base_dir
        self.max_log_size = max_log_size or (3 * 1024 * 1024)
        self._locks: Dict[str, threading.Lock] = {}
        self._handles: Dict[str, Any] = {}
        self._write_counts: Dict[str, int] = {}
        self._global_lock = threading.Lock()
        os.makedirs(self.base_dir, exist_ok=True)
    
    def _get_lock(self, item_uuid: str) -> threading.Lock:
        with self._global_lock:
            if item_uuid not in self._locks:
                self._locks[item_uuid] = threading.Lock()
            return self._locks[item_uuid]

    def get_log_path(self, item_uuid: str) -> str:
        return os.path.join(self.base_dir, f"{item_uuid}.log")

    def _get_handle(self, item_uuid: str):
        handle = self._handles.get(item_uuid)
        if handle is not None and not handle.closed:
            return handle
        log_path = self.get_log_path(item_uuid)
        handle = open(log_path, "a", encoding="utf-8")
        self._handles[item_uuid] = handle
        self._write_counts[item_uuid] = 0
        return handle

    def _maybe_rotate(self, item_uuid: str) -> None:
        count = self._write_counts.get(item_uuid, 0) + 1
        self._write_counts[item_uuid] = count
        if count % self.ROTATION_CHECK_INTERVAL != 0:
            return
        log_path = self.get_log_path(item_uuid)
        try:
            if os.path.exists(log_path) and os.path.getsize(log_path) >= self.max_log_size:
                handle = self._handles.pop(item_uuid, None)
                if handle and not handle.closed:
                    handle.close()
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("=== 日志文件已超出最大大小，已清空 ===\\n\\n")
        except OSError:
            pass

    def write_to_log(self, item_uuid: str, content: str) -> bool:
        lock = self._get_lock(item_uuid)
        with lock:
            try:
                self._maybe_rotate(item_uuid)
                handle = self._get_handle(item_uuid)
                handle.write(content)
                handle.flush()
                return True
            except Exception as e:
                logger.error(f"Failed to write log for terminal {item_uuid}: {e}")
                handle = self._handles.pop(item_uuid, None)
                if handle and not handle.closed:
                    try:
                        handle.close()
                    except OSError:
                        pass
                return False

    def close_log(self, item_uuid: str) -> None:
        lock = self._get_lock(item_uuid)
        with lock:
            handle = self._handles.pop(item_uuid, None)
            if handle and not handle.closed:
                try:
                    handle.close()
                except OSError:
                    pass

    def delete_log(self, item_uuid: str) -> bool:
        self.close_log(item_uuid)
        try:
            log_path = self.get_log_path(item_uuid)
            if os.path.exists(log_path):
                os.remove(log_path)
            return True
        except Exception as e:
            logger.error(f"Failed to delete log for terminal {item_uuid}: {e}")
            return False'''

content = content.replace(old_log_manager, new_log_manager)

# === FIX 4: Add watchdog + store thread ref ===
# In start(), after starting _read_output thread, store ref and start watchdog
content = content.replace(
    "                threading.Thread(target=self._read_output, daemon=True).start()",
    "                self._reader_thread = threading.Thread(target=self._read_output, daemon=True)\n"
    "                self._reader_thread.start()\n"
    "                threading.Thread(target=self._watchdog, daemon=True).start()"
)

# Add watchdog method before _read_output
watchdog_method = '''
    def _watchdog(self):
        """Periodically check if _read_output thread is alive; mark stopped if dead."""
        import time as _time
        while self._running:
            _time.sleep(5)
            reader = getattr(self, "_reader_thread", None)
            if reader is not None and not reader.is_alive() and self._running:
                logger.error(
                    f"[Terminal] _read_output thread died unexpectedly for {self.item_uuid}, marking stopped"
                )
                self._running = False
                self.status = "stopped"
                self._broadcast({"exit": True, "exit_code": self._collect_exit_code()})
                break

'''

content = content.replace(
    "    def _read_output(self):",
    watchdog_method + "    def _read_output(self):"
)

# === FIX 5: Close log handle on stop ===
content = content.replace(
    '            self._write_log(f"[{datetime.now().strftime(\'%Y-%m-%d %H:%M:%S\')}] Terminal stopped\\n")',
    '            self._write_log(f"[{datetime.now().strftime(\'%Y-%m-%d %H:%M:%S\')}] Terminal stopped\\n")\n'
    '            daemon_log_manager.close_log(self.item_uuid)'
)

with open(f, "w", encoding="utf-8") as fh:
    fh.write(content)

print("All fixes applied")