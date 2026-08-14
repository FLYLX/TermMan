# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for name, old, new in pairs:
        c = s.count(old)
        assert c == 1, f"{name}: anchor count={c} in {path}"
        s = s.replace(old, new)
        print(f"{name}: replaced OK")
    open(path, "w", encoding="utf-8", newline="").write(s)

INT = r"E:\dev\TermPaws\dev\TermPaws\backend\app\plugins\robot\agent\integration.py"
CTX = r"E:\dev\TermPaws\dev\TermPaws\backend\app\plugins\robot\mcp\context.py"

patch(INT, [
    ("source_route_contract",
     '"- reply contract: reply to the current QQ conversation by outputting the reply text directly; the system auto-delivers it back to this conversation. Only call mcp_robot_send_message when sending to a different conversation or multiple targets. Do not leave the answer only in the TermPaws web chat.\\n"',
     '"- reply contract: to reply to the current QQ conversation, call `mcp_robot_send_message` in your current response (pass only `text`; it is routed to this conversation automatically). Do not end the turn with plain reply text - final text is NOT auto-delivered. Do not leave the answer only in the TermPaws web chat.\\n"'),
    ("ticket_reply_routing",
     '            "- REPLY ROUTING: output your reply text directly and the system "\n            "auto-delivers it back to this QQ conversation. Only call "\n            "`mcp_robot_send_message` when sending to a different conversation "\n            "or multiple targets. Do not leave answers only in TermPaws.\\n"',
     '            "- REPLY ROUTING: to reply to this QQ conversation, call "\n            "`mcp_robot_send_message` in your current response (pass only `text`). "\n            "Plain final text is NOT auto-delivered. Do not leave answers only in TermPaws.\\n"'),
])

patch(CTX, [
    ("private_send_rule",
     '                    "- send rule: to reply, output your reply text directly and the system "\n                    "auto-delivers it back to this conversation; only call "\n                    "`mcp_robot_send_message` when sending to a different conversation or "\n                    "multiple targets. Private chat is addressed to you; reply directly. "\n                    "If this turn should not be replied to, call "\n                    "`mcp_robot_sleep_conversation` instead."',
     '                    "- send rule: to reply, call `mcp_robot_send_message` in your current "\n                    "response with only `text` (it is routed to this conversation automatically); "\n                    "plain final text is NOT auto-delivered. Private chat is addressed to you; "\n                    "reply directly. If this turn should not be replied to, call "\n                    "`mcp_robot_sleep_conversation` instead."'),
    ("group_send_rule",
     '"- send rule: to reply to this current QQ conversation, output your reply text directly and the system auto-delivers it back to this conversation; only call `mcp_robot_send_message` when sending to a different conversation or multiple targets. Reply when the current message "',
     '"- send rule: to reply to this current QQ conversation, call `mcp_robot_send_message` in your current response with only `text` (routed to this conversation automatically); plain final text is NOT auto-delivered. Reply when the current message "'),
])
print("ALL DONE")
