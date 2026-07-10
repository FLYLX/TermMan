import os
import re
import select
import signal
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from core import config, get_socket_service
from service.item_path_service import ItemPathError, item_path_service
from service.terminal_manager import daemon_log_manager
from utils.logger import logger


class JobRunnerError(Exception):
    pass


@dataclass
class ActiveJob:
    job_id: str
    item_uuid: str
    command: str
    pid: int
    started_at: datetime
    cancel_requested: bool = False


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ERROR_HINT_RE = re.compile(
    r"\b(?:error|failed|failure|exception|traceback|denied|not found|timed out|timeout|aborted|cancelled)\b",
    re.IGNORECASE,
)
PROGRESS_LINE_PATTERNS = (
    re.compile(r"^\s*%\s+Total\s+%\s+Received\b", re.IGNORECASE),
    re.compile(
        r"^\s*\d{1,3}\s+\d+(?:\.\d+)?[kmg]?\s+\d{1,3}\s+\d+(?:\.\d+)?[kmg]?\s+\d{1,3}\s+",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*\d{1,3}%\|.*\|"),
    re.compile(r".*\d{1,3}%.*(?:\[[\s=>#.-]+\]|[=#>]{2,}|\|.*\|).*"),
    re.compile(r"^\s*\d+(?:\.\d+)?\s*[KMG]B?\s+.*\d{1,3}%", re.IGNORECASE),
    re.compile(
        r"^\s*(?:downloading|downloaded|fetching|receiving|extracting|installing|building|preparing)\b.*(?:\d{1,3}%|\d+(?:\.\d+)?\s*(?:kb|mb|gb)|/s|it/s)",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:get|hit|ign):\d+\s+", re.IGNORECASE),
    re.compile(r"^\s*(?:\||/|-|\\)\s*$"),
    re.compile(r"^\s*(?:\||/|-|\\)\s+(?:download|fetch|install|build|extract)\b", re.IGNORECASE),
)


def _strip_terminal_controls(value: str) -> str:
    value = ANSI_ESCAPE_RE.sub("", value or "")
    value = value.replace("\b", "")
    value = CONTROL_CHARS_RE.sub("", value)
    return value


def is_progress_noise_line(line: str) -> bool:
    stripped = _strip_terminal_controls(line).strip()
    if not stripped:
        return False
    if ERROR_HINT_RE.search(stripped):
        return False
    if any(pattern.match(stripped) for pattern in PROGRESS_LINE_PATTERNS):
        return True
    return bool(
        re.search(r"\d{1,3}%", stripped)
        and re.search(r"(?:/s|eta|remaining|\[[\s=>#.-]+\])", stripped, re.IGNORECASE)
    )


class JobRunner:
    DEFAULT_TIMEOUT_SECONDS = 600
    MAX_TIMEOUT_SECONDS = 3600
    DEFAULT_TAIL_LINES = 80
    MAX_TAIL_LINES = 300

    def __init__(self):
        self.encoding = config.get("TERMINAL_ENCODING", "utf-8")
        self._active_jobs: dict[str, ActiveJob] = {}
        self._jobs_lock = threading.RLock()

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
        cancelled = False
        cancel_terminate_sent = False
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
            self._register_active_job(
                item_uuid=item_uuid,
                job_id=job_id,
                command=command,
                pid=pid,
                started_at=started_at,
            )

            pending_line = ""
            while True:
                now = time.monotonic()
                if self._is_cancel_requested(job_id):
                    cancelled = True
                    if not cancel_terminate_sent:
                        cancel_terminate_sent = True
                        logger.warning(
                            f"[JobRunner] Job cancel requested: job_id={job_id} pid={pid} command={command!r}"
                        )
                        self._terminate_process(pid)

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
            self._unregister_active_job(job_id)
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
            f"  Cancelled: {cancelled}\n"
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
                "cancelled": cancelled,
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
            "cancelled": cancelled,
            "duration_seconds": duration_seconds,
            "output_tail": output_tail,
            "tail_lines": len(tail),
            "output_bytes": output_bytes,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        }

    def list_jobs(self, *, item_uuid: str | None = None) -> dict[str, Any]:
        now = datetime.now()
        with self._jobs_lock:
            jobs = [
                {
                    "job_id": job.job_id,
                    "item_uuid": job.item_uuid,
                    "command": job.command,
                    "pid": job.pid,
                    "started_at": job.started_at.isoformat(),
                    "elapsed_seconds": round((now - job.started_at).total_seconds(), 3),
                    "cancel_requested": job.cancel_requested,
                }
                for job in self._active_jobs.values()
                if item_uuid is None or job.item_uuid == item_uuid
            ]
        jobs.sort(key=lambda job: str(job.get("started_at") or ""), reverse=True)
        return {
            "success": True,
            "jobs": jobs,
            "count": len(jobs),
            "item_uuid": item_uuid,
        }

    def cancel_job(self, *, item_uuid: str, job_id: str | None = None) -> dict[str, Any]:
        with self._jobs_lock:
            active_job = None
            if job_id:
                candidate = self._active_jobs.get(job_id)
                if candidate and candidate.item_uuid == item_uuid:
                    active_job = candidate
            else:
                active_job = next(
                    (job for job in self._active_jobs.values() if job.item_uuid == item_uuid),
                    None,
                )

            if not active_job:
                return {
                    "success": False,
                    "cancelled": False,
                    "error": "No running job for item",
                    "item_uuid": item_uuid,
                    "job_id": job_id or "",
                }

            active_job.cancel_requested = True
            pid = active_job.pid
            resolved_job_id = active_job.job_id
            command = active_job.command

        logger.warning(
            f"[JobRunner] Cancelling active job: job_id={resolved_job_id} item={item_uuid} pid={pid}"
        )
        self._terminate_process(pid)
        return {
            "success": True,
            "cancelled": True,
            "item_uuid": item_uuid,
            "job_id": resolved_job_id,
            "command": command,
        }

    def _register_active_job(
        self,
        *,
        item_uuid: str,
        job_id: str,
        command: str,
        pid: int,
        started_at: datetime,
    ) -> None:
        with self._jobs_lock:
            self._active_jobs[job_id] = ActiveJob(
                job_id=job_id,
                item_uuid=item_uuid,
                command=command,
                pid=pid,
                started_at=started_at,
            )

    def _unregister_active_job(self, job_id: str) -> None:
        with self._jobs_lock:
            self._active_jobs.pop(job_id, None)

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._jobs_lock:
            active_job = self._active_jobs.get(job_id)
            return bool(active_job and active_job.cancel_requested)

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
        if is_progress_noise_line(clean_line):
            return
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
            delivered = False
            try:
                child_pgid = os.getpgid(pid)
                if child_pgid != os.getpgrp():
                    os.killpg(child_pgid, sig)
                    delivered = True
                else:
                    logger.debug(
                        f"[JobRunner] Skip process-group signal {sig} for pid={pid}; child shares daemon pgid"
                    )
            except ProcessLookupError:
                return
            except Exception as exc:
                logger.debug(f"[JobRunner] Failed to send signal {sig} to process group for pid={pid}: {exc}")

            if not delivered:
                try:
                    os.kill(pid, sig)
                    delivered = True
                except ProcessLookupError:
                    return
                except Exception as exc:
                    logger.warning(f"[JobRunner] Failed to send signal {sig} to pid={pid}: {exc}")

            if delivered and delay:
                time.sleep(delay)

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