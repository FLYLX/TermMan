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


def _allow_backend_room_socket(monkeypatch) -> None:
    class ConnectedRoomSocket:
        def is_connected(self):
            return True

    monkeypatch.setattr(
        http_routes.daemon_conn_pool,
        "get_backend_room_listen_conn",
        lambda item_uuid: ConnectedRoomSocket() if item_uuid == "item-1" else None,
    )


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


def test_get_item_job_result_returns_runner_payload(monkeypatch) -> None:
    class FakeJobRunner:
        def get_job_result(self, job_id):
            assert job_id == "job-1"
            return {
                "success": True,
                "status": "finished",
                "result": {"exit_code": 0},
            }

    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())

    result = http_routes.get_item_job_result(
        "item-1",
        http_routes.InternalJobResultRequest(job_id="job-1"),
        _api_key="test",
    )

    assert result["status"] == "finished"
    assert result["result"]["exit_code"] == 0


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
        def start_job(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "job_id": "job-1"}

    monkeypatch.setattr(http_routes, "terminal_manager", FakeTerminalManager())
    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())
    monkeypatch.setattr(
        http_routes.room_manager,
        "has_permanent_subscribers",
        lambda item_uuid: item_uuid == "item-1",
    )
    _allow_backend_room_socket(monkeypatch)

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


def test_run_item_job_rejects_terminal_without_backend_room(monkeypatch) -> None:
    class FakeTerminalManager:
        def get_terminal_status(self, item_uuid):
            assert item_uuid == "item-1"
            return {"status": "running"}

    class FakeJobRunner:
        def run_job(self, **_kwargs):
            raise AssertionError("job runner must not start without a Backend Room")

    monkeypatch.setattr(http_routes, "terminal_manager", FakeTerminalManager())
    monkeypatch.setattr(http_routes, "job_runner", FakeJobRunner())
    monkeypatch.setattr(
        http_routes.room_manager,
        "has_permanent_subscribers",
        lambda _item_uuid: False,
    )

    with pytest.raises(HTTPException) as exc_info:
        http_routes.run_item_job(
            "item-1",
            http_routes.InternalJobRunRequest(
                user_uuid="user-1",
                command="ls",
            ),
            _api_key="test",
        )

    assert exc_info.value.status_code == 409
    assert "Backend Item Room" in str(exc_info.value.detail)
