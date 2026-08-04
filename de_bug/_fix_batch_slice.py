# -*- coding: utf-8 -*-
p = r"backend\app\plugins\robot\service.py"
raw = open(p, encoding="utf-8", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")
old = "        for entry in entries[:PENDING_CHAT_QUEUE_LIMIT]:"
assert t.count(old) == 1, "expected exactly 1 occurrence, found %d" % t.count(old)
t = t.replace(old, "        for entry in entries[-PENDING_CHAT_QUEUE_LIMIT:]:")
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("batch text latest-N fixed")
