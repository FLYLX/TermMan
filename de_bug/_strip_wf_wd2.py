# -*- coding: utf-8 -*-
from pathlib import Path
path = Path(r"backend\app\services\agent\task_watchdog.py")
src = path.read_text(encoding="utf-8")

def rep(old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, f"expected {count}, found {n}: {old[:70]!r}"
    src = src.replace(old, new)

rep('''def _remove_orphan_tickets(now: datetime, stats: dict[str, int]) -> None:
    from app.services.agent.reply_ticket import TICKET_TTL, reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    inactive_cutoff = now - TICKET_TTL''',
'''def _remove_orphan_tickets(now: datetime, stats: dict[str, int]) -> None:
    from app.services.agent.reply_ticket import TICKET_TTL, reply_ticket_manager

    inactive_cutoff = now - TICKET_TTL''')

rep('''        updated_at = _as_utc(ticket.updated_at)
        workflow = task_workflow_manager.get_by_ticket(ticket.ticket_id)
        if workflow is not None:
            continue
        if updated_at >= inactive_cutoff:''',
'''        updated_at = _as_utc(ticket.updated_at)
        if updated_at >= inactive_cutoff:''')

# module docstring cleanup
i = src.find('"""Watchdog that closes out stale, non-final task workflows.')
j = src.find('"""', i + 3)
assert i >= 0 and j > i
src = src[:i] + '''"""Watchdog that keeps agent task state tidy.

Closes stale orphan reply tickets, removes tickets past their TTL, dedupes
near-duplicate long-term memories, reaps stuck dispatch jobs, and sweeps
pending inputs so queued messages always start a turn.

All work is best-effort: individual failures are logged and never stop the
scan.
"""''' + src[j+3:]

path.write_text(src, encoding="utf-8")
print("watchdog final cleanup ok")
