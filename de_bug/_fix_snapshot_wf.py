import pathlib
p = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\reply_ticket.py")
text = p.read_text(encoding="utf-8")
old = '                    "conversation_generation": ticket.conversation_generation,\n                    "workflow": workflow,\n'
new = '                    "conversation_generation": ticket.conversation_generation,\n                    "workflow": None,\n'
assert text.count(old) == 1
text = text.replace(old, new)
p.write_text(text, encoding="utf-8")
print("snapshot workflow field fixed")
