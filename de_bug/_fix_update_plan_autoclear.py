import pathlib
p = pathlib.Path(r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\mcp\local_server.py")
text = p.read_text(encoding="utf-8")
old = '''        all_completed = all(item["status"] == "completed" for item in normalized)
        # Keep plan on ticket for UI history (don't clear when all completed).
        reply_ticket_manager.update_ticket_plan(ticket.ticket_id, normalized)
        try:
            from app.services.agent.stream_manager import stream_manager

            stream_manager.broadcast_chat_event(
                item_id,
                {
                    "type": "plan_updated",
                    "item_id": item_id,
                    "plan": normalized,
                    "explanation": str(args.get("explanation") or ""),
                },
            )
        except Exception:
            pass
'''
new = '''        all_completed = all(item["status"] == "completed" for item in normalized)
        # Once every step is completed, broadcast the final all-completed
        # snapshot once, then clear the plan from the ticket so finished work
        # leaves the plan table immediately (no extra plan=[] call needed).
        reply_ticket_manager.update_ticket_plan(
            ticket.ticket_id, [] if all_completed else normalized
        )
        try:
            from app.services.agent.stream_manager import stream_manager

            stream_manager.broadcast_chat_event(
                item_id,
                {
                    "type": "plan_updated",
                    "item_id": item_id,
                    "plan": normalized,
                    "explanation": "completed"
                    if all_completed
                    else str(args.get("explanation") or ""),
                },
            )
        except Exception:
            pass
'''
assert text.count(old) == 1
text = text.replace(old, new)
p.write_text(text, encoding="utf-8")
print("update_plan auto-clear on all completed: done")
