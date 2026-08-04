# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/api/routes/chat.py", 990, 1015),
    ("backend/app/api/routes/chat.py", 2280, 2315),
    ("backend/app/plugins/robot/agent/integration.py", 512, 540),
    ("backend/app/services/agent/task_watchdog.py", 100, 175),
]
for path, start, end in REGIONS:
    print(f"\n===== {path} [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
