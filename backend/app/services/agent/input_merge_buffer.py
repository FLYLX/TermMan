"""System-level input merge buffer.

Buffers inputs that arrive while an agent turn is running and merges them
into one consolidated batch for the next turn, instead of one turn per input.

Any input source can use it: QQ messages, background job results, terminal
output, scheduled inputs, and future sources. Entries keep their full source
metadata (source type, sender, time, ticket/workflow references, and an
opaque routing payload) so merging never loses who said what or where the
result belongs.

Scope: entries are grouped per (item_id, scope_key). The item scope is used
for web/terminal sessions; the conversation scope (scope_key = QQ
conversation key) keeps different QQ conversations on the same item apart.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_QQ_MESSAGE = "qq_message"
SOURCE_JOB_RESULT = "job_result"
SOURCE_TERMINAL_OUTPUT = "terminal_output"
SOURCE_SCHEDULED_TASK = "scheduled_task"

# Per-source retention caps inside one scope. Overflow evicts the oldest
# entries (returned to the caller so the source can log/act on the eviction).
DEFAULT_SOURCE_LIMITS: dict[str, int] = {
    SOURCE_QQ_MESSAGE: 10,
    SOURCE_JOB_RESULT: 8,
    SOURCE_TERMINAL_OUTPUT: 20,
    SOURCE_SCHEDULED_TASK: 8,
    "default": 8,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def scope_buffer_key(item_id: str, scope_key: str = "") -> str:
    return f"{item_id}|{scope_key}" if scope_key else str(item_id)


@dataclass(frozen=True)
class MergeBufferEntry:
    source_type: str
    item_id: str
    scope_key: str = ""
    sender_label: str = ""
    sender_key: str = ""
    content: str = ""
    enqueued_at: datetime = field(default_factory=_utcnow)
    reply_ticket_id: str = ""
    payload: Any = None


class InputMergeBuffer:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, list[MergeBufferEntry]] = {}
        self._source_limits: dict[str, int] = dict(DEFAULT_SOURCE_LIMITS)

    def set_source_limit(self, source_type: str, limit: int) -> None:
        with self._lock:
            self._source_limits[source_type] = max(1, int(limit))

    def add(self, entry: MergeBufferEntry) -> tuple[int, list[MergeBufferEntry]]:
        """Buffer an entry.

        Returns (pending_size, evicted_entries) for the entry's scope so the
        source can surface evictions instead of silently dropping them.
        """
        with self._lock:
            key = scope_buffer_key(entry.item_id, entry.scope_key)
            entries = list(self._entries.get(key) or [])
            entries.append(entry)
            limit = self._source_limits.get(
                entry.source_type,
                self._source_limits["default"],
            )
            evicted: list[MergeBufferEntry] = []
            if len(entries) > limit:
                evicted = entries[: len(entries) - limit]
                entries = entries[len(entries) - limit :]
                logger.info(
                    "[InputMergeBuffer] Evicted %s oldest %s entries for %s (limit %s)",
                    len(evicted),
                    entry.source_type,
                    key,
                    limit,
                )
            self._entries[key] = entries
            return len(entries), evicted

    def prepend(
        self,
        item_id: str,
        scope_key: str,
        entries: list[MergeBufferEntry],
    ) -> None:
        """Put entries back at the front (e.g. a follow-up enqueue failed)."""
        if not entries:
            return
        with self._lock:
            key = scope_buffer_key(item_id, scope_key)
            self._entries[key] = list(entries) + list(self._entries.get(key) or [])

    def pop(self, item_id: str, scope_key: str = "") -> list[MergeBufferEntry]:
        """Drain all buffered entries for a scope (used on turn end/merge)."""
        with self._lock:
            return self._entries.pop(scope_buffer_key(item_id, scope_key), [])

    def pop_all_for_item(self, item_id: str) -> list[MergeBufferEntry]:
        """Drain every buffered scope belonging to an item.

        Turn-end drains must not be limited to the ending turn's own
        conversation: entries of other conversations buffered while the turn
        ran would otherwise linger until a turn for their own conversation
        happens to end (which may never come).
        """
        item_key = str(item_id)
        prefix = f"{item_key}|"
        with self._lock:
            drained: list[MergeBufferEntry] = []
            keys = [
                key
                for key in self._entries
                if key == item_key or key.startswith(prefix)
            ]
            for key in keys:
                drained.extend(self._entries.pop(key, []))
            return drained

    def distinct_item_ids(self) -> list[str]:
        """Item ids that currently have buffered entries (any scope)."""
        with self._lock:
            ids: set[str] = set()
            for key in self._entries:
                ids.add(key.split("|", 1)[0])
            return sorted(ids)

    def peek(self, item_id: str, scope_key: str = "") -> list[MergeBufferEntry]:
        with self._lock:
            return list(self._entries.get(scope_buffer_key(item_id, scope_key), []))

    def count(self, item_id: str, scope_key: str = "") -> int:
        with self._lock:
            return len(self._entries.get(scope_buffer_key(item_id, scope_key), []))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


input_merge_buffer = InputMergeBuffer()
