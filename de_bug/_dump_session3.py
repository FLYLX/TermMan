# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/services/agent/session.py", 1000, 1030),
    ("backend/app/services/agent/session.py", 1125, 1160),
    ("backend/app/services/agent/session.py", 2124, 2165),
    ("backend/app/services/agent/session.py", 2405, 2445),
    ("backend/app/services/agent/session.py", 2555, 2600),
    ("backend/app/services/agent/session.py", 3210, 3268),
]
for path, start, end in REGIONS:
    print(f"\n===== [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
