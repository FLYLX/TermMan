# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/services/agent/mcp/local_server.py", 75, 95),
    ("backend/app/services/agent/mcp/local_server.py", 530, 585),
    ("backend/app/services/agent/mcp/local_server.py", 1323, 1400),
    ("backend/app/services/agent/mcp/local_server.py", 2040, 2165),
    ("backend/app/services/agent/state_restore.py", 1, 60),
]
for path, start, end in REGIONS:
    print(f"\n===== {path} [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
