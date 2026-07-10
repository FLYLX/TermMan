import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if sys.platform == "win32":
    fake_pty = types.ModuleType("pty")
    fake_pty.fork = lambda: (_ for _ in ()).throw(NotImplementedError("pty is not available on Windows"))
    sys.modules.setdefault("pty", fake_pty)

    fake_fcntl = types.ModuleType("fcntl")
    fake_fcntl.ioctl = lambda *args, **kwargs: 0
    sys.modules.setdefault("fcntl", fake_fcntl)

    fake_termios = types.ModuleType("termios")
    fake_termios.TIOCSWINSZ = 0
    fake_termios.TIOCGWINSZ = 0
    sys.modules.setdefault("termios", fake_termios)

sys.path.append(str(Path(__file__).resolve().parent / "src"))

from api import socket_routes


class FakeDaemonConnPool:
    def get_all_browser_terminal_conns(self):
        return {"item-1": [SimpleNamespace(sid="browser-sid")]}

    def get_all_backend_room_listen_conns(self):
        return []


class FakeTerminal:
    def __init__(self):
        self.writes = []

    def write(self, command):
        self.writes.append(command)
        return True


class FakeTerminalManager:
    def __init__(self, terminal):
        self.terminal = terminal

    def get_terminal(self, item_uuid):
        assert item_uuid == "item-1"
        return self.terminal


class FakeSocketService:
    def __init__(self):
        self.broadcasts = []

    def sync_broadcast(self, item_uuid, event, data):
        self.broadcasts.append((item_uuid, event, data))


def test_browser_terminal_write_broadcasts_stdin(monkeypatch):
    terminal = FakeTerminal()
    socket_service = FakeSocketService()

    monkeypatch.setattr(socket_routes, "daemon_conn_pool", FakeDaemonConnPool())
    monkeypatch.setattr(socket_routes, "terminal_manager", FakeTerminalManager(terminal))
    monkeypatch.setattr(socket_routes, "socket_service", socket_service)

    asyncio.run(socket_routes.on_terminal_write("browser-sid", {"command": "ls"}))

    assert terminal.writes == ["ls\n"]
    assert socket_service.broadcasts == [
        (
            "item-1",
            "stream",
            {
                "stdin": "ls\n",
                "stdout": "",
                "stderr": "",
                "source": "browser",
            },
        )
    ]



def test_browser_ctrl_c_cancels_active_job_before_terminal_write(monkeypatch):
    terminal = FakeTerminal()
    socket_service = FakeSocketService()
    cancelled = []

    class FakeJobRunner:
        def cancel_job(self, **kwargs):
            cancelled.append(kwargs)
            return {"success": True, "cancelled": True, "job_id": "job-1"}

    monkeypatch.setattr(socket_routes, "daemon_conn_pool", FakeDaemonConnPool())
    monkeypatch.setattr(socket_routes, "terminal_manager", FakeTerminalManager(terminal))
    monkeypatch.setattr(socket_routes, "socket_service", socket_service)
    monkeypatch.setattr(socket_routes, "job_runner", FakeJobRunner())

    asyncio.run(socket_routes.on_terminal_write("browser-sid", {"command": "\x03"}))

    assert cancelled == [{"item_uuid": "item-1"}]
    assert terminal.writes == []
    assert socket_service.broadcasts == [
        (
            "item-1",
            "stream",
            {
                "stdin": "^C\n",
                "stdout": "\u540e\u53f0\u4efb\u52a1\u5df2\u4e2d\u65ad\u3002\n",
                "stderr": "",
                "source": "browser",
                "job_cancelled": True,
                "job_id": "job-1",
            },
        )
    ]


def test_internal_job_run_route_delegates_to_job_runner(monkeypatch):
    from api import http_routes

    captured = {}

    class FakeJobRunner:
        def run_job(self, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "job_id": "job-1",
                "exit_code": 0,
                "output_tail": "done",
            }

    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())

    payload = http_routes.InternalJobRunRequest(
        user_uuid="user-1",
        command="echo done",
        working_directory="workdir",
        timeout_seconds=30,
        tail_lines=7,
        env={"A": "B"},
    )
    result = http_routes.run_item_job("item-1", payload, _api_key="ok")

    assert result["success"] is True
    assert result["output_tail"] == "done"
    assert captured == {
        "user_uuid": "user-1",
        "item_uuid": "item-1",
        "command": "echo done",
        "working_directory": "workdir",
        "timeout_seconds": 30,
        "tail_lines": 7,
        "env": {"A": "B"},
    }


def test_internal_job_list_route_delegates_to_job_runner(monkeypatch):
    from api import http_routes

    captured = {}

    class FakeJobRunner:
        def list_jobs(self, **kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "jobs": [{"job_id": "job-1", "command": "apt-get update"}],
                "count": 1,
            }

    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())

    result = http_routes.list_item_jobs("item-1", _api_key="ok")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["jobs"][0]["job_id"] == "job-1"
    assert captured == {"item_uuid": "item-1"}

def test_job_runner_filters_progress_noise_from_tail(monkeypatch):
    from collections import deque

    from service.job_runner import JobRunner, is_progress_noise_line

    written: list[str] = []
    runner = JobRunner()
    monkeypatch.setattr(runner, "_write_job_log", lambda item_uuid, content: written.append(content))
    tail: deque[str] = deque(maxlen=20)

    progress_lines = [
        "  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current",
        "  0     0    0     0    0     0      0      0 --:--:--  0:00:20 --:--:--     0",
        "45%|####5     | 45/100 [00:01<00:01, 30.00it/s]",
    ]
    for line in progress_lines:
        assert is_progress_noise_line(line) is True
        runner._append_output_line("item-1", "job-1", line, tail)

    runner._append_output_line("item-1", "job-1", "TEMURIN_DOWNLOAD_DONE", tail)
    runner._append_output_line("item-1", "job-1", "curl: (28) Connection timed out", tail)

    assert list(tail) == ["TEMURIN_DOWNLOAD_DONE", "curl: (28) Connection timed out"]
    assert len(written) == 2


def test_job_runner_background_env_is_non_interactive():
    from service.job_runner import JobRunner

    env = JobRunner()._build_child_env(None)

    assert env["TERM"] == "dumb"
    assert env["DEBIAN_FRONTEND"] == "noninteractive"
    assert env["APT_LISTCHANGES_FRONTEND"] == "none"
    assert env["NEEDRESTART_MODE"] == "a"
    assert env["GPG_TTY"] == ""
    assert env["PYTHONUNBUFFERED"] == "1"


def test_job_runner_starts_non_interactive_subprocess(monkeypatch):
    import importlib
    import subprocess

    from service.job_runner import JobRunner

    job_runner_module = importlib.import_module("service.job_runner")
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.pid = 1234
            self.stdout = None

    monkeypatch.setattr(job_runner_module.config, "get", lambda key, default=None: default)
    monkeypatch.setattr(job_runner_module.subprocess, "Popen", FakePopen)

    process = JobRunner()._start_process("/tmp", "echo ok", None)

    assert process.pid == 1234
    assert captured["args"] == ["/bin/bash", "-lc", "echo ok"]
    assert captured["kwargs"]["cwd"] == "/tmp"
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is subprocess.PIPE
    assert captured["kwargs"]["stderr"] is subprocess.STDOUT
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["env"]["DEBIAN_FRONTEND"] == "noninteractive"


def test_internal_job_cancel_route_delegates_to_job_runner(monkeypatch):
    from api import http_routes

    captured = {}

    class FakeJobRunner:
        def cancel_job(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "cancelled": True, "job_id": kwargs["job_id"]}

    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())

    payload = http_routes.InternalJobCancelRequest(job_id="job-1")
    result = http_routes.cancel_item_job("item-1", payload, _api_key="ok")

    assert result == {"success": True, "cancelled": True, "job_id": "job-1"}
    assert captured == {"item_uuid": "item-1", "job_id": "job-1"}



def test_job_runner_list_jobs_filters_by_item(monkeypatch):
    from datetime import datetime, timedelta

    from service.job_runner import JobRunner

    runner = JobRunner()
    started_at = datetime.now() - timedelta(seconds=8)
    runner._register_active_job(
        item_uuid="item-1",
        job_id="job-1",
        command="apt-get update",
        pid=1234,
        started_at=started_at,
    )
    runner._register_active_job(
        item_uuid="item-2",
        job_id="job-2",
        command="bun install",
        pid=5678,
        started_at=started_at,
    )

    try:
        result = runner.list_jobs(item_uuid="item-1")
    finally:
        runner._unregister_active_job("job-1")
        runner._unregister_active_job("job-2")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["jobs"][0]["job_id"] == "job-1"
    assert result["jobs"][0]["elapsed_seconds"] >= 0

def test_job_runner_cancel_job_marks_active_job(monkeypatch):
    from datetime import datetime

    from service.job_runner import JobRunner

    runner = JobRunner()
    killed: list[int] = []
    monkeypatch.setattr(runner, "_terminate_process", lambda pid: killed.append(pid))

    runner._register_active_job(
        item_uuid="item-1",
        job_id="job-1",
        command="apt-get install -y temurin-17-jdk",
        pid=1234,
        started_at=datetime.now(),
    )
    result = runner.cancel_job(item_uuid="item-1")

    assert result["success"] is True
    assert result["cancelled"] is True
    assert result["job_id"] == "job-1"
    assert runner._is_cancel_requested("job-1") is True
    assert killed == [1234]
    runner._unregister_active_job("job-1")
