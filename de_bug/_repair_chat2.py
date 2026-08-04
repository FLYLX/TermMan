# -*- coding: utf-8 -*-
from pathlib import Path
path = Path(r"backend\app\api\routes\chat.py")
src = path.read_text(encoding="utf-8")

def rep(old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, f"expected {count}, found {n}: {old[:70]!r}"
    src = src.replace(old, new)

rep('''    if ticket:
        task_workflow_manager.update(
            ticket_id,
            action="cancel",
            note=str(reason or final_report)[:2000],
        )
        reply_ticket_manager.mark_failed(ticket_id, reason or final_report)''',
'''    if ticket:
        reply_ticket_manager.mark_failed(ticket_id, reason or final_report)''')

rep("\n                                    ticket_events = _deliver_reply_ticket_final_response(",
    "\n                    ticket_events = _deliver_reply_ticket_final_response(")

rep('if stop_after_final_robot_delivery:\n                                    _broadcast_agent_status(item_id, "idle")',
    'if stop_after_final_robot_delivery:\n                    _broadcast_agent_status(item_id, "idle")')

path.write_text(src, encoding="utf-8")
print("fixed")
