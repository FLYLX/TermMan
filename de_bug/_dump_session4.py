# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/services/agent/session.py", encoding="utf-8").read().splitlines()
for start, end in [(2405, 2446), (2540, 2572), (2600, 2640)]:
    print(f"\n===== [{start}-{end}] =====")
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
import re
src = "\n".join(lines)
for m in re.finditer(r"_update_pending_reply_waiting\(", src):
    print("CALLER", src[:m.start()].count("\n")+1)
