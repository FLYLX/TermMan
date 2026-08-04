# -*- coding: utf-8 -*-
from pathlib import Path

def patch(path_str, pairs):
    path = Path(path_str)
    src = path.read_text(encoding="utf-8")
    for old, new, count in pairs:
        n = src.count(old)
        assert n == count, f"{path_str}: expected {count}, found {n}: {old[:70]!r}"
        src = src.replace(old, new)
    path.write_text(src, encoding="utf-8")
    print(f"patched {path_str}")

# ---------- reply_ticket.py ----------
patch(r"backend\app\services\agent\reply_ticket.py", [
('''    def mark_delivered(self, ticket_id: str) -> bool:
        ticket_id = self.resolve_ticket_id(ticket_id)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            # Hard constraint: if the report already reached the user via
            # the send tool, skip the can_finalize gate and force-close.
            pre_ticket = self.get(ticket_id)
            if not (pre_ticket and pre_ticket.external_report_sent):
                can_finalize, reason = task_workflow_manager.can_finalize(ticket_id)
                if not can_finalize:
                    if task_workflow_manager.complete_final_step_on_delivery(ticket_id):
                        can_finalize, reason = task_workflow_manager.can_finalize(ticket_id)
                if not can_finalize:
                    logger.info(
                        "[ReplyTicket] Kept ticket active after intermediate delivery: ticket=%s reason=%s",
                        ticket_id,
                        reason,
                    )
                    return False
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to validate workflow delivery state: ticket=%s",
                ticket_id,
            )
            return False

        ticket = self.get(ticket_id)
        if ticket is not None:
            # A delivered conclusion also closes any last-step workflow in this
            # item, even when this ticket was never attached to it.
            task_workflow_manager.complete_last_step_workflow_on_delivery(
                ticket.item_id
            )

        with self._lock:''',
'''    def mark_delivered(self, ticket_id: str) -> bool:
        ticket_id = self.resolve_ticket_id(ticket_id)

        with self._lock:''', 1),
('''            ticket.delivery_error = ""
            _persist_ticket(ticket)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.on_delivery(ticket_id)
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to complete task workflow after delivery: ticket=%s",
                ticket_id,
            )
        return True''',
'''            ticket.delivery_error = ""
            _persist_ticket(ticket)
        return True''', 1),
('''        from app.services.agent.task_workflow import task_workflow_manager

        with self._lock:
            now = datetime.now()
            candidates = []''',
'''        with self._lock:
            now = datetime.now()
            candidates = []''', 1),
('''                wf = task_workflow_manager.get_by_ticket(ticket.ticket_id)
                if wf and wf.status in {"cancelled", "failed"}:
                    continue
''', '', 1),
('''            self._tickets.clear()
            self._ticket_aliases.clear()
            _persist_aliases(self._ticket_aliases)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.reset()
        except Exception:
            pass''',
'''            self._tickets.clear()
            self._ticket_aliases.clear()
            _persist_aliases(self._ticket_aliases)''', 1),
])

# ---------- session.py ----------
patch(r"backend\app\services\agent\session.py", [
('''    def schedule_task_workflow_continuation(self, ticket_id: str) -> bool:
        normalized_ticket_id = str(ticket_id or "").strip()
        if not normalized_ticket_id:
            return False
        if not task_workflow_manager.claim_auto_resume(normalized_ticket_id):
            return False
        input_msg = InputMessage(
            input_type=InputType.TASK_CONTINUATION,
            content=(
                "[Internal task workflow continuation]\\n"
                "Resume the authoritative workflow from its current step. Execute one "
                "concrete safe action now; do not provide a next-step narration."
            ),
            query="Resume the unfinished authoritative task workflow with one concrete action.",
            reply_ticket_id=normalized_ticket_id,
        )
        threading.Thread(
            target=self.process_input,
            args=(input_msg,),
            daemon=True,
        ).start()
        return True

''', '', 1),
])

# ---------- state_restore.py ----------
path = Path(r"backend\app\services\agent\state_restore.py")
path.write_text('''"""Restore persisted agent task state after a backend restart."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def restore_agent_state() -> dict[str, int]:
    restored = {"tickets": 0}
    try:
        from app.services.agent.reply_ticket import restore_tickets_from_store

        restored["tickets"] = restore_tickets_from_store()
    except Exception:
        logger.exception("[StateRestore] Failed to restore reply tickets")
    if any(restored.values()):
        logger.info(
            "[StateRestore] Restored tickets=%s",
            restored["tickets"],
        )
    return restored
''', encoding="utf-8")
print("rewrote state_restore.py")

# ---------- utils.py ----------
patch(r"backend\app\api\routes\utils.py", [
('''    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager
    from app.services.agent.session import agent_session_manager''',
'''    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.session import agent_session_manager''', 1),
('''    out["tickets"] = safe(lambda: len(reply_ticket_manager._tickets))
    out["workflows"] = safe(lambda: len(task_workflow_manager._workflows))
    out["sessions"] = safe(lambda: len(agent_session_manager._sessions))''',
'''    out["tickets"] = safe(lambda: len(reply_ticket_manager._tickets))
    out["sessions"] = safe(lambda: len(agent_session_manager._sessions))''', 1),
])

# ---------- tool_selection.py ----------
patch(r"backend\app\services\agent\tool_selection.py", [
('''        "mcp_local_update_plan",
        "mcp_local_update_task_workflow",
        "mcp_local_get_task_workflow",
        PREPARE_CAPABILITIES_TOOL,''',
'''        "mcp_local_update_plan",
        PREPARE_CAPABILITIES_TOOL,''', 1),
])
print("ALL OK")
