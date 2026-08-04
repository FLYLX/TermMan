from pathlib import Path

path = Path(r"backend\app\api\routes\chat.py")
src = path.read_text(encoding="utf-8")

old = '''    if is_no_reply_intent(content):
        # The agent chose silence (e.g. bare "NRN" on a job callback); never
        # deliver the marker itself. Ticket lifecycle stays untouched.
        return []'''

new = '''    if is_no_reply_intent(content):
        # The agent chose silence (e.g. bare "NRN" on a job callback); never
        # deliver the marker itself. Finalize as completed so the ticket does
        # not linger as "running" on the task board.
        reply_ticket_manager.mark_completed(ticket_id)
        return []'''

count = src.count(old)
assert count == 1, f"expected exactly 1 match, found {count}"
path.write_text(src.replace(old, new), encoding="utf-8")
print("patched ok")
