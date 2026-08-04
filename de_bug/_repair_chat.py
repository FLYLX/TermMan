# -*- coding: utf-8 -*-
import re
from pathlib import Path

path = Path(r"backend\app\api\routes\chat.py")
src = path.read_text(encoding="utf-8")

def rep(old, new="", count=1):
    global src
    n = src.count(old)
    assert n == count, f"expected {count}, found {n} for: {old[:70]!r}"
    src = src.replace(old, new)

def drop_orphan_body(start_marker, end_marker):
    """Delete from start_marker line to the line containing end_marker (exclusive)."""
    global src
    i = src.find(start_marker)
    assert i >= 0, f"start not found: {start_marker[:60]!r}"
    j = src.find(end_marker, i)
    assert j >= 0, f"end not found: {end_marker[:60]!r}"
    src = src[:i] + src[j:]

# 1. orphaned _plan_agent_task_titles tail (from stray sig line to next top-level def)
drop_orphan_body(") -> list[str]:\n    prefers_chinese = _contains_cjk(message)", "def _current_task_origin(")

# 2. orphaned _complete_agent_task_plan body
rep('''plan: PlannedTaskRuntime | None) -> None:
    if not plan:
        return

    workflow = task_workflow_manager.get(plan.workflow_id)
    if workflow and workflow.status not in {
        "ready_to_report",
        "completed",
        "cancelled",
    }:
        return

    if plan.reply_ticket_id:
        reply_ticket_manager.mark_completed(plan.reply_ticket_id)


''')

# 3. orphaned _mark_agent_task_plan_failed body
rep(''') -> None:
    if not plan:
        return

    if plan.reply_ticket_id and plan.workflow_id:
        task_workflow_manager.update(
            plan.reply_ticket_id,
            action="cancel",
            note=reason,
        )

    if plan.reply_ticket_id:
        reply_ticket_manager.mark_failed(plan.reply_ticket_id, reason)

''')

# 4. orphaned _create_agent_task_plan body (up to _append_conversation_memory)
i = src.find(") -> PlannedTaskRuntime | None:")
assert i >= 0
j = src.find("def _append_conversation_memory(", i)
assert j >= 0
src = src[:i] + src[j:]

# 5. remaining call sites
rep("    _complete_agent_task_plan(planned_task_runtime)\n", "", count=2)
rep('''            if planned_task_runtime:
                planned_task_runtime.tool_started = True
''')
rep("                    _mark_agent_task_plan_failed(planned_task_runtime)\n", "", count=2)
rep('''                    delivery_is_final, _ = task_workflow_manager.can_finalize(
                        reply_ticket.ticket_id
                    )
                    if delivery_is_final:
                        delivery_tool_sent_by_integration = True
                        reply_ticket_manager.mark_delivered(
                            reply_ticket.ticket_id
                        )
                    else:
                        task_workflow_manager.update(
                            reply_ticket.ticket_id,
                            action="record_progress",
                            note="Sent an intermediate status update; the main task remains active.",
                        )''',
'''                    delivery_tool_sent_by_integration = True
                    reply_ticket_manager.mark_delivered(
                        reply_ticket.ticket_id
                    )''')

remaining = [l for l in src.splitlines() if "task_workflow" in l or "PlannedTaskRuntime" in l or "planned_task_runtime" in l]
print("REMAINING:", len(remaining))
for l in remaining[:10]:
    print("  ", l.strip()[:110])
path.write_text(src, encoding="utf-8")
print("repair written")
