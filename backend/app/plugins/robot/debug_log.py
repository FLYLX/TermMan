from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

MAX_EVENTS_PER_ROBOT = 200

_lock = threading.RLock()
_events: dict[str, deque[dict[str, Any]]] = defaultdict(
    lambda: deque(maxlen=MAX_EVENTS_PER_ROBOT)
)


def record_robot_event(
    robot_id: str,
    *,
    direction: str,
    event: str,
    status: str = "ok",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": direction,
        "event": event,
        "status": status,
        "message": message,
        "payload": payload or {},
    }
    with _lock:
        _events[str(robot_id)].appendleft(entry)


def get_robot_events(robot_id: str, limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, MAX_EVENTS_PER_ROBOT))
    with _lock:
        return list(_events.get(str(robot_id), []))[:safe_limit]
