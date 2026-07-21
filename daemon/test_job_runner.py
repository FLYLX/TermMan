import sys
import types
from pathlib import Path

if sys.platform == "win32":
    fake_pty = types.ModuleType("pty")
    fake_pty.fork = lambda: (_ for _ in ()).throw(
        NotImplementedError("pty is not available on Windows")
    )
    sys.modules.setdefault("pty", fake_pty)

    fake_fcntl = types.ModuleType("fcntl")
    fake_fcntl.ioctl = lambda *args, **kwargs: 0
    sys.modules.setdefault("fcntl", fake_fcntl)

    fake_termios = types.ModuleType("termios")
    fake_termios.TIOCSWINSZ = 0
    fake_termios.TIOCGWINSZ = 0
    sys.modules.setdefault("termios", fake_termios)

sys.path.append(str(Path(__file__).resolve().parent / "src"))

from service.job_runner import JobRunner


def test_get_job_result_returns_buffered_result() -> None:
    runner = JobRunner()
    runner._store_finished_result(
        "job-1", {"success": True, "job_id": "job-1", "exit_code": 0}
    )

    finished = runner.get_job_result("job-1")
    assert finished["success"] is True
    assert finished["status"] == "finished"
    assert finished["result"]["exit_code"] == 0

    unknown = runner.get_job_result("missing")
    assert unknown["success"] is False
    assert unknown["status"] == "unknown"


def test_get_job_result_reports_running_active_job() -> None:
    runner = JobRunner()
    runner._register_active_job(
        item_uuid="item-1",
        job_id="job-live",
        command="sleep 60",
        pid=12345,
        started_at=None,
        output_tail=None,
    )

    assert runner.get_job_result("job-live")["status"] == "running"


def test_finished_result_expires_after_ttl() -> None:
    runner = JobRunner()
    runner._finished_results["job-old"] = (0.0, {"success": True, "job_id": "job-old"})

    assert runner.get_job_result("job-old")["status"] == "unknown"


def test_start_job_rejects_empty_command() -> None:
    runner = JobRunner()
    result = runner.start_job(command="   ")
    assert result["success"] is False
    assert result["job_id"]
