# -*- coding: utf-8 -*-
from pathlib import Path

def patch_file(path_str, pairs):
    path = Path(path_str)
    src = path.read_text(encoding="utf-8")
    for old, new, count in pairs:
        n = src.count(old)
        assert n == count, f"{path_str}: expected {count}, found {n}: {old[:70]!r}"
        src = src.replace(old, new)
    path.write_text(src, encoding="utf-8")
    print(f"patched {path_str}")

# ---------- builder.py ----------
B = r"backend\app\services\agent\prompts\builder.py"
path = Path(B)
src = path.read_text(encoding="utf-8")
src = src.replace("from app.services.agent.task_workflow import task_workflow_manager\n", "")
i = src.find("def _build_active_task_ledger_context(")
assert i >= 0
j = src.find("def _dedupe_adjacent_messages(", i)
assert j >= 0
src = src[:i] + src[j:]
block = '''    active_task_ledger_context = _build_active_task_ledger_context(item_id, agent)
    if active_task_ledger_context:
        extra_prompt_parts.append(active_task_ledger_context)
'''
n = src.count(block)
assert n == 2, f"expected 2 usage blocks, found {n}"
src = src.replace(block, "")
path.write_text(src, encoding="utf-8")
print(f"patched {B}")

# ---------- reply_ticket.py ----------
patch_file(r"backend\app\services\agent\reply_ticket.py", [
('''        if new_ticket.source_type != SOURCE_QQ or not new_ticket.conversation_key:
            return
        try:
            from app.services.agent.task_workflow import task_workflow_manager
        except Exception:
            return
        for ticket in list(self._tickets.values()):''',
'''        if new_ticket.source_type != SOURCE_QQ or not new_ticket.conversation_key:
            return
        for ticket in list(self._tickets.values()):''', 1),
('''            if ticket.plan:
                continue
            try:
                if task_workflow_manager.get_by_ticket(ticket.ticket_id) is not None:
                    continue
            except Exception:
                continue
            if ticket.external_report_sent:''',
'''            if ticket.plan:
                continue
            if ticket.external_report_sent:''', 1),
('''                _persist_ticket(current)
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                task_workflow_manager.mark_delivery_failed(ticket_id, str(exc))
            except Exception:
                pass
            return False''',
'''                _persist_ticket(current)
            return False''', 1),
('''        for ticket in tickets:
            workflow = None
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                workflow = task_workflow_manager.snapshot_for_ticket(ticket.ticket_id)
            except Exception:
                pass
            snapshots.append(''',
'''        for ticket in tickets:
            snapshots.append(''', 1),
('''                    "pending_reply_status": str(
                        (workflow or {}).get("queue_status") or ""
                    ),
                    "pending_reply_requester": str(
                        (workflow or {}).get("requester") or ""
                    ),
                    "pending_reply_plan": [
                        str(step.get("title") or "")
                        for step in (workflow or {}).get("steps") or []
                        if isinstance(step, dict) and step.get("title")
                    ],
                    "pending_reply_awaiting_kind": str(
                        (workflow or {}).get("awaiting_kind") or ""
                    ),
                    "pending_reply_awaiting_key": str(
                        (workflow or {}).get("awaiting_key") or ""
                    ),''',
'''                    "pending_reply_status": "",
                    "pending_reply_requester": "",
                    "pending_reply_plan": [],
                    "pending_reply_awaiting_kind": "",
                    "pending_reply_awaiting_key": "",''', 1),
])

# ---------- main.py ----------
patch_file(r"backend\app\api\main.py", [
("    task_workflows,\n", "", 1),
("api_router.include_router(task_workflows.router)\n", "", 1),
])
print("ALL OK")
