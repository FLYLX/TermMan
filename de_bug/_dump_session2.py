# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/services/agent/session.py", 2220, 2270),
    ("backend/app/services/agent/session.py", 2458, 2480),
    ("backend/app/services/agent/session.py", 2576, 2625),
    ("backend/app/services/agent/session.py", 3210, 3300),
    ("backend/app/services/agent/session.py", 3330, 3360),
    ("backend/app/services/agent/session.py", 3460, 3490),
]
for path, start, end in REGIONS:
    print(f"\n===== [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
