# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/services/agent/prompts/builder.py", 25, 35),
    ("backend/app/services/agent/prompts/builder.py", 805, 850),
    ("backend/app/services/agent/reply_ticket.py", 295, 332),
    ("backend/app/services/agent/reply_ticket.py", 725, 800),
]
for path, start, end in REGIONS:
    print(f"\n===== {path.split('/')[-1]} [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
