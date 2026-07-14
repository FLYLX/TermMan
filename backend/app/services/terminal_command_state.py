from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TerminalCommandState:
    item_id: str
    command: str
    source: str
    sent_at: str
    expected_output: str = ""
    expected_regex: str = ""
    timeout_seconds: int = 0


class TerminalCommandStateManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, TerminalCommandState] = {}

    def record(
        self,
        item_id: str,
        command: str,
        *,
        source: str,
        expected_output: str = "",
        expected_regex: str = "",
        timeout_seconds: int = 0,
    ) -> dict:
        item_key = str(item_id or "").strip()
        command_text = str(command or "").strip()
        if not item_key or not command_text or command_text == "\x03":
            return self.snapshot(item_key)

        state = TerminalCommandState(
            item_id=item_key,
            command=command_text[:4000],
            source=str(source or "unknown").strip()[:32] or "unknown",
            sent_at=_utcnow().isoformat(),
            expected_output=str(expected_output or "").strip()[:1000],
            expected_regex=str(expected_regex or "").strip()[:2000],
            timeout_seconds=max(int(timeout_seconds or 0), 0),
        )
        with self._lock:
            self._states[item_key] = state
        return asdict(state)

    def snapshot(self, item_id: str) -> dict:
        item_key = str(item_id or "").strip()
        with self._lock:
            state = self._states.get(item_key)
        if not state:
            return {
                "item_id": item_key,
                "command": "",
                "source": "",
                "sent_at": "",
                "expected_output": "",
                "expected_regex": "",
                "timeout_seconds": 0,
            }
        return asdict(state)

    def build_prompt_context(self, item_id: str) -> str:
        state = self.snapshot(item_id)
        command = str(state.get("command") or "").strip()
        if not command:
            return ""

        expected = str(state.get("expected_output") or "").strip()
        expected_regex = str(state.get("expected_regex") or "").strip()
        expectation_line = ""
        if expected:
            expectation_line = f"Expected output text: {expected}. "
        elif expected_regex:
            expectation_line = f"Expected output regex: {expected_regex}. "

        return (
            "Last terminal command sent for this item:\n"
            f"{command}\n"
            f"Command source: {state.get('source') or 'unknown'}. "
            f"{expectation_line}"
            "Use this command together with the newest terminal output when diagnosing. "
            "A missing expected match is not proof that the process failed. "
            "Do not interrupt the process unless the user explicitly requested cancellation."
        )

    def clear(self, item_id: str) -> None:
        with self._lock:
            self._states.pop(str(item_id or "").strip(), None)


terminal_command_state_manager = TerminalCommandStateManager()
