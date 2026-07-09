import os
import select
import signal
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Optional

from core import config, get_socket_service
from service.item_path_service import ItemPathError, item_path_service
from service.terminal_manager import daemon_log_manager
from utils.logger import logger


class JobRunnerError(Exception):
    pass


class JobRunner:
    DEFAULT_TIMEOUT_SECONDS = 600
    MAX_TIMEOUT_SECONDS = 3600
    DEFAULT_TAIL_LINES = 80
    MAX_TAIL_LINES = 300

    def __init__(self):
        self.encoding = config.get("TERMINAL_ENCODING", "utf-8")

    def run_job(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        command: str,
        working_directory: Optional[str] = None,
        timeout_seconds: int | float | None = None,
        tail_lines: int | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        command = (command or "").strip()
        if not command:
            return {"success": False, "error": "command is required", "job_id": job_id}

        timeout = self._coerce_timeout(timeout_seconds)
        tail_limit = self._coerce_tail_lines(tail_lines)
        started_at = datetime.now()
        start_monotonic = time.monotonic()
        pid: int | None = None
        master_fd: int | None = None
        timed_out = False
        exit_code: int | None = None
        tail = deque(maxlen=tail_limit)
        output_bytes = 0
        read_iterations = 0
        cwd = ""

        logger.info(
            f"[JobRunner] Starting job: job_id={job_id} item={item_uuid} user={user_uuid} "
            f"timeout={timeout} tail_lines={tail_limit} command={command!r} "
            f"working_directory={working_directory!r}"
        )

        try:
            cwd = self._resolve_workdir(user_uuid, item_uuid, working_directory)
            self._write_job_log(
                item_uuid,
                f"\n{'=' * 60}\n"
                f"[{started_at.strftime('%Y-%m-%d %H:%M:%S')}] Job started\n"
                f"  Job ID: {job_id}\n"
                f"  Working Directory: {cwd}\n"
                f"  Command: {command}\n"
                f"{'=' * 60}\n",
            )
            self._broadcast(
                item_uuid,
                {
                    "stdout": f"[{started_at.strftime('%Y-%m-%d %H:%M:%S')}] Job started: {command}\n",
                    "stderr": "",
                    "source": "job",
                    "job_id": job_id,
                    "status": "running",
                },
            )

            pty_module = self._get_pty_module()
            pid, master_fd = pty_module.fork()
            if pid == 0:
                try:
                    self._exec_child(cwd, command, env)
                except Exception as child_exc:
                    os.write(2, f"Job exec failed: {child_exc}\n".encode(self.encoding, errors="replace"))
                    os._exit(127)

            os.set_blocking(master_fd, False)
            logger.info(f"[JobRunner] PTY forked: job_id={job_id} pid={pid} cwd={cwd}")

            pending_line = ""
            while True:
                now = time.monotonic()
                if now - start_monotonic > timeout:
                    timed_out = True
                    logger.warning(
                        f"[JobRunner] Job timeout: job_id={job_id} pid={pid} timeout={timeout} command={command!r}"
                    )
                    self._terminate_process(pid)

                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except BlockingIOError:
                        chunk = b""
                    except OSError:
                        chunk = b""

                    if chunk:
                        read_iterations += 1
                        output_bytes += len(chunk)
                        decoded = chunk.decode(self.encoding, errors="replace")
                        pending_line = self._handle_output_chunk(
                            item_uuid=item_uuid,
                            job_id=job_id,
                            decoded=decoded,
                            pending_line=pending_line,
                            tail=tail,
                        )

                wait_pid, status = os.waitpid(pid, os.WNOHANG)
                if wait_pid == pid:
                    exit_code = self._status_to_exit_code(status)
                    logger.info(
                        f"[JobRunner] Job process exited: job_id={job_id} pid={pid} "
                        f"exit_code={exit_code} timed_out={timed_out}"
                    )
                    break

                if timed_out:
                    wait_pid, status = os.waitpid(pid, 0)
                    exit_code = self._status_to_exit_code(status)
                    break

            if pending_line.strip():
                self._append_output_line(item_uuid, job_id, pending_line, tail)

        except Exception as exc:
            logger.error(f"[JobRunner] Job failed before completion: job_id={job_id} item={item_uuid} error={exc}")
            return {
                "success": False,
                "error": str(exc),
                "job_id": job_id,
                "item_uuid": item_uuid,
                "command": command,
                "cwd": cwd,
            }
        finally:
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except Exception:
                    pass

        finished_at = datetime.now()
        duration_seconds = round(time.monotonic() - start_monotonic, 3)
        exit_code = exit_code if exit_code is not None else -1
        output_tail = "\n".join(tail)
        footer = (
            f"\n{'=' * 60}\n"
            f"[{finished_at.strftime('%Y-%m-%d %H:%M:%S')}] Job finished\n"
            f"  Job ID: {job_id}\n"
            f"  Exit Code: {exit_code}\n"
            f"  Timed Out: {timed_out}\n"
            f"  Duration: {duration_seconds}s\n"
            f"{'=' * 60}\n"
        )
        self._write_job_log(item_uuid, footer)
        self._broadcast(
            item_uuid,
            {
                "stdout": footer,
                "stderr": "",
                "source": "job",
                "job_id": job_id,
                "status": "finished",
                "exit_code": exit_code,
                "timed_out": timed_out,
            },
        )
        logger.info(
            f"[JobRunner] Job completed: job_id={job_id} item={item_uuid} exit_code={exit_code} "
            f"timed_out={timed_out} duration={duration_seconds} output_bytes={output_bytes} "
            f"read_iterations={read_iterations} tail_lines={len(tail)}"
        )
        return {
            "success": True,
            "job_id": job_id,
            "item_uuid": item_uuid,
            "command": command,
            "cwd": cwd,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_seconds": duration_seconds,
            "output_tail": output_tail,
            "tail_lines": len(tail),
            "output_bytes": output_bytes,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        }

    def _get_pty_module(self):
        try:
            import pty
        except ImportError as exc:
            raise JobRunnerError("daemon job runner requires POSIX pty support") from exc
        return pty

    def _resolve_workdir(self, user_uuid: str, item_uuid: str, working_directory: str | None) -> str:
        try:
            return str(
                item_path_service.resolve_workdir(
                    user_uuid=user_uuid,
                    item_uuid=item_uuid,
                    working_directory=working_directory,
                    create=True,
                )
            )
        except ItemPathError as exc:
            raise JobRunnerError(f"invalid working_directory: {exc}") from exc

    def _exec_child(self, cwd: str, command: str, env: dict[str, str] | None):
        os.chdir(cwd)
        child_env = os.environ.copy()
        child_env.update(
            {
                "TERM": "xterm-256color",
                "COLUMNS": "120",
                "LINES": "30",
                "LANG": child_env.get("LANG", "C.UTF-8"),
                "LC_ALL": child_env.get("LC_ALL", "C.UTF-8"),
                "LC_CTYPE": child_env.get("LC_CTYPE", child_env.get("LC_ALL", "C.UTF-8")),
                "PYTHONUTF8": child_env.get("PYTHONUTF8", "1"),
                "PYTHONIOENCODING": child_env.get("PYTHONIOENCODING", "utf-8"),
            }
        )
        if env:
            child_env.update({str(key): str(value) for key, value in env.items()})
        os.environ.clear()
        os.environ.update(child_env)
        shell = config.get("TERMINAL_SHELL", "/bin/bash")
        os.execvp(shell, [shell, "-lc", command])

    def _handle_output_chunk(
        self,
        *,
        item_uuid: str,
        job_id: str,
        decoded: str,
        pending_line: str,
        tail: deque[str],
    ) -> str:
        text = decoded.replace("\r\n", "\n")
        self._broadcast(
            item_uuid,
            {
                "stdout": text,
                "stderr": "",
                "source": "job",
                "job_id": job_id,
                "status": "running",
            },
        )
        pending_line += text.replace("\r", "\n")
        lines = pending_line.split("\n")
        pending_line = lines[-1]
        for line in lines[:-1]:
            if line.strip():
                self._append_output_line(item_uuid, job_id, line, tail)
        return pending_line

    def _append_output_line(self, item_uuid: str, job_id: str, line: str, tail: deque[str]):
        clean_line = line.rstrip("\n")
        tail.append(clean_line)
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        self._write_job_log(item_uuid, f"{timestamp} [job:{job_id}] {clean_line}\n")

    def _write_job_log(self, item_uuid: str, content: str):
        if not daemon_log_manager.write_to_log(item_uuid, content):
            logger.warning(f"[JobRunner] Failed to write daemon log: item={item_uuid}")

    def _broadcast(self, item_uuid: str, data: dict[str, Any]):
        try:
            socket_service = get_socket_service()
            if socket_service:
                socket_service.sync_broadcast(item_uuid, "stream", data)
        except Exception as exc:
            logger.error(f"[JobRunner] Broadcast failed: item={item_uuid} error={exc}")

    def _terminate_process(self, pid: int | None):
        if pid is None:
            return
        for sig, delay in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 0.0)):
            try:
                os.kill(pid, sig)
                if delay:
                    time.sleep(delay)
            except ProcessLookupError:
                return
            except Exception as exc:
                logger.warning(f"[JobRunner] Failed to send signal {sig} to pid={pid}: {exc}")

    def _status_to_exit_code(self, status: int) -> int:
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return -os.WTERMSIG(status)
        return -1

    def _coerce_timeout(self, value: int | float | None) -> int:
        try:
            timeout = int(float(value)) if value is not None else self.DEFAULT_TIMEOUT_SECONDS
        except (TypeError, ValueError):
            timeout = self.DEFAULT_TIMEOUT_SECONDS
        return max(1, min(timeout, self.MAX_TIMEOUT_SECONDS))

    def _coerce_tail_lines(self, value: int | None) -> int:
        try:
            lines = int(value) if value is not None else self.DEFAULT_TAIL_LINES
        except (TypeError, ValueError):
            lines = self.DEFAULT_TAIL_LINES
        return max(1, min(lines, self.MAX_TAIL_LINES))


job_runner = JobRunner()