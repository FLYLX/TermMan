import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

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

from api import http_routes


@pytest.mark.parametrize("terminal_status", [None, {"status": "stopped"}])
def test_run_item_job_requires_active_main_terminal(
    monkeypatch,
    terminal_status,
) -> None:
    class FakeTerminalManager:
        def get_terminal_status(self, item_uuid):
            assert item_uuid == "item-1"
            return terminal_status

    class FakeJobRunner:
        def run_job(self, **_kwargs):
            raise AssertionError("job runner must not start while main terminal is stopped")

    monkeypatch.setattr(http_routes, "terminal_manager", FakeTerminalManager())
    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())

    with pytest.raises(HTTPException) as exc_info:
        http_routes.run_item_job(
            "item-1",
            http_routes.InternalJobRunRequest(
                user_uuid="user-1",
                command="java -version",
            ),
            _api_key="test",
        )

    assert exc_info.value.status_code == 409
    assert "Main terminal is not running" in str(exc_info.value.detail)


def test_run_item_job_allows_active_main_terminal(monkeypatch) -> None:
    captured = {}

    class FakeTerminalManager:
        def get_terminal_status(self, item_uuid):
            assert item_uuid == "item-1"
            return {"status": "running"}

        def get_terminal_current_workdir(self, item_uuid):
            assert item_uuid == "item-1"
            return "/workspace/item"

    class FakeJobRunner:
        def run_job(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "job_id": "job-1"}

    monkeypatch.setattr(http_routes, "terminal_manager", FakeTerminalManager())
    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())

    result = http_routes.run_item_job(
        "item-1",
        http_routes.InternalJobRunRequest(
            user_uuid="user-1",
            command="java -version",
        ),
        _api_key="test",
    )

    assert result == {"success": True, "job_id": "job-1"}
    assert captured["working_directory"] == "/workspace/item"
