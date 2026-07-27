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
                "timeout_seconds": 0,
            }
        return asdict(state)

    def build_prompt_context(self, item_id: str) -> str:
        state = self.snapshot(item_id)
        command = str(state.get("command") or "").strip()
        if not command:
            return ""

        return (
            "Last terminal command sent for this item:\n"
            f"{command}\n"
            f"Command source: {state.get('source') or 'unknown'}. "
            "Use this command together with the newest terminal output when diagnosing. "
            "Do not interrupt the process unless the user explicitly requested cancellation."
        )

    def clear(self, item_id: str) -> None:
        with self._lock:
            self._states.pop(str(item_id or "").strip(), None)


terminal_command_state_manager = TerminalCommandStateManager()