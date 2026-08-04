# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 1) reply_intent.py: recognize bare NRN (the token our own callback templates teach)
p1 = r"E:\dev\TermMan\dev\TermMan\backend\app\plugins\robot\reply_intent.py"
s1 = open(p1, encoding="utf-8").read()
old1 = '    "silent",\n    "silence",\n}'
new1 = '    "silent",\n    "silence",\n    "nrn",\n}'
assert s1.count(old1) == 1, f"intent anchor={s1.count(old1)}"
s1 = s1.replace(old1, new1)
open(p1, "w", encoding="utf-8", newline="").write(s1)
print("reply_intent: OK")

# 2) chat.py: NRN guard in ticket fallback delivery
p2 = r"E:\dev\TermMan\dev\TermMan\backend\app\api\routes\chat.py"
s2 = open(p2, encoding="utf-8").read()
old2 = '''    from app.plugins.robot.internal_trace import sanitize_robot_visible_text

    ticket_id = str(reply_ticket_id or "").strip() or _current_reply_ticket_id(agent)
    ticket = reply_ticket_manager.get(ticket_id)
    if not ticket or ticket.source_type != SOURCE_QQ:
        return []
    if ticket.external_report_sent:'''
new2 = '''    from app.plugins.robot.internal_trace import sanitize_robot_visible_text
    from app.plugins.robot.reply_intent import is_no_reply_intent

    ticket_id = str(reply_ticket_id or "").strip() or _current_reply_ticket_id(agent)
    ticket = reply_ticket_manager.get(ticket_id)
    if not ticket or ticket.source_type != SOURCE_QQ:
        return []
    if is_no_reply_intent(content):
        # The agent chose silence (e.g. bare "NRN" on a job callback); never
        # deliver the marker itself. Ticket lifecycle stays untouched.
        return []
    if ticket.external_report_sent:'''
assert s2.count(old2) == 1, f"chat anchor={s2.count(old2)}"
s2 = s2.replace(old2, new2)
open(p2, "w", encoding="utf-8", newline="").write(s2)
print("chat fallback guard: OK")
