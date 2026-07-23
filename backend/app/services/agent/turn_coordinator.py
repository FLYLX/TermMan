from __future__ import annotations

import asyncio
import threading
import uuid
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


def agent_turn_key(handler_id: str) -> str:
    return f"handler:{str(handler_id)}"


@dataclass
class AgentTurnLease:
    coordinator: AgentTurnCoordinator
    key: str
    token: str
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self.coordinator.release(self)


class AgentTurnCoordinator:
    """Serializes all turns that share one mutable Agent instance."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._queues: dict[str, deque[str]] = defaultdict(deque)
        self._active: dict[str, str] = {}

    def _enqueue(self, key: str) -> str:
        token = uuid.uuid4().hex
        with self._condition:
            self._queues[key].append(token)
            self._condition.notify_all()
        return token

    def _try_claim(self, key: str, token: str) -> bool:
        with self._condition:
            queue = self._queues.get(key)
            if not queue or queue[0] != token or key in self._active:
                return False
            queue.popleft()
            if not queue:
                self._queues.pop(key, None)
            self._active[key] = token
            return True

    def _cancel_waiter(self, key: str, token: str) -> None:
        with self._condition:
            queue = self._queues.get(key)
            if queue and token in queue:
                queue.remove(token)
                if not queue:
                    self._queues.pop(key, None)
            self._condition.notify_all()

    def acquire(self, key: str) -> AgentTurnLease:
        normalized_key = str(key)
        token = self._enqueue(normalized_key)
        with self._condition:
            while not self._try_claim(normalized_key, token):
                self._condition.wait()
        return AgentTurnLease(self, normalized_key, token)

    async def acquire_async(self, key: str, timeout_seconds: float = 150.0) -> AgentTurnLease:
        normalized_key = str(key)
        token = self._enqueue(normalized_key)
        import time as _time

        deadline = _time.monotonic() + timeout_seconds
        try:
            while not self._try_claim(normalized_key, token):
                if _time.monotonic() > deadline:
                    self._cancel_waiter(normalized_key, token)
                    raise TimeoutError(
                        f"Turn coordinator: timed out waiting for lock "
                        f"after {timeout_seconds}s (key={normalized_key}). "
                        f"A previous turn may be stuck on an LLM call."
                    )
                await asyncio.sleep(0.025)
        except BaseException:
            self._cancel_waiter(normalized_key, token)
            raise
        return AgentTurnLease(self, normalized_key, token)

    def release(self, lease: AgentTurnLease) -> None:
        with self._condition:
            if self._active.get(lease.key) == lease.token:
                self._active.pop(lease.key, None)
            self._condition.notify_all()

    @contextmanager
    def turn(self, key: str) -> Iterator[AgentTurnLease]:
        lease = self.acquire(key)
        try:
            yield lease
        finally:
            lease.release()

    def reset(self) -> None:
        with self._condition:
            self._queues.clear()
            self._active.clear()
            self._condition.notify_all()


agent_turn_coordinator = AgentTurnCoordinator()
