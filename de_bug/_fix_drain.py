# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def patch(path, repls):
    src = open(path, encoding="utf-8").read()
    for old, new in repls:
        n = src.count(old)
        if n != 1:
            print(f"FAIL {path}: anchor count={n} for {old[:70]!r}")
            sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print(f"OK {path}: {len(repls)} replacement(s)")

BUF = r"backend\app\services\agent\input_merge_buffer.py"
LS = r"backend\app\services\agent\mcp\local_server.py"
SVC = r"backend\app\plugins\robot\service.py"
SESS = r"backend\app\services\agent\session.py"
TC = r"backend\app\services\agent\turn_coordinator.py"

patch(BUF, [
(
'''    def pop(self, item_id: str, scope_key: str = "") -> list[MergeBufferEntry]:
        """Drain all buffered entries for a scope (used on turn end/merge)."""
        with self._lock:
            return self._entries.pop(scope_buffer_key(item_id, scope_key), [])
''',
'''    def pop(self, item_id: str, scope_key: str = "") -> list[MergeBufferEntry]:
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
'''
),
])

patch(LS, [
(
'''def flush_job_results_for_turn_end(item_id: str, conversation_key: str = "") -> bool:
    entries = _pop_buffered_job_results(item_id, conversation_key)
    return flush_background_job_results_for_entries(item_id, entries)
''',
'''def flush_job_results_for_turn_end(item_id: str, conversation_key: str = "") -> bool:
    entries = _pop_buffered_job_results(item_id, conversation_key)
    return flush_background_job_results_for_entries(item_id, entries)


def flush_all_job_results_for_item(item_id: str) -> int:
    """Drain every buffered job result of an item at turn end.

    Results are grouped per conversation so each conversation gets exactly
    one merged follow-up turn, but no conversation's results can be stranded
    by a turn that belongs to a different conversation.
    """
    drained = [
        entry.payload
        for entry in input_merge_buffer.pop_all_for_item(str(item_id))
        if entry.payload is not None
    ]
    if not drained:
        return 0
    by_conversation: dict[str, list[dict[str, Any]]] = {}
    for entry in drained:
        key = str(entry.get("conversation_key") or "")
        by_conversation.setdefault(key, []).append(entry)
    flushed = 0
    for entries in by_conversation.values():
        if flush_background_job_results_for_entries(str(item_id), entries):
            flushed += len(entries)
    if flushed:
        debug_log(
            f"[LocalMCPServer] turn-end item flush: item={item_id} "
            f"drained={len(drained)} flushed={flushed} "
            f"conversations={len(by_conversation)}"
        )
    return flushed
'''
),
# double-check after buffering: drain item-wide, not just this conversation
(
'''                if not _conversation_turn_busy(agent_session, robot_job_context):
                    flush_job_results_for_turn_end(
                        item_id,
                        str(entry.get("conversation_key") or ""),
                    )''',
'''                if not _conversation_turn_busy(agent_session, robot_job_context):
                    flush_all_job_results_for_item(item_id)'''
),
])

patch(SVC, [
(
'''                try:
                    from app.services.agent.mcp.local_server import (
                        flush_job_results_for_turn_end,
                    )

                    flush_job_results_for_turn_end(
                        str(job.item_id),
                        conversation_key=job.conversation_key,
                    )
                except Exception:
                    logger.debug(
                        "[RobotService] Failed to flush buffered job results for item=%s",
                        job.item_id,
                    )''',
'''                try:
                    from app.services.agent.mcp.local_server import (
                        flush_all_job_results_for_item,
                    )

                    flush_all_job_results_for_item(str(job.item_id))
                except Exception:
                    logger.debug(
                        "[RobotService] Failed to flush buffered job results for item=%s",
                        job.item_id,
                    )'''
),
])

patch(SESS, [
(
'''        try:
            from app.services.agent.mcp.local_server import (
                flush_job_results_for_turn_end,
            )

            flush_job_results_for_turn_end(self.item_id)
        except Exception:
            pass''',
'''        try:
            from app.services.agent.mcp.local_server import (
                flush_all_job_results_for_item,
            )

            flush_all_job_results_for_item(self.item_id)
        except Exception:
            pass'''
),
])

patch(TC, [
(
'''    async def acquire_async(self, key: str, timeout_seconds: float = 150.0) -> AgentTurnLease:''',
'''    async def acquire_async(self, key: str, timeout_seconds: float = 230.0) -> AgentTurnLease:'''
),
])
print("DRAIN+TIMEOUT FIX APPLIED")
