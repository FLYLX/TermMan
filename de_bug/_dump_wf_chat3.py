# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/api/routes/chat.py", 1915, 1955),
    ("backend/app/api/routes/chat.py", 2335, 2370),
    ("backend/app/services/agent/mcp/local_server.py", 95, 145),
]
for path, start, end in REGIONS:
    print(f"\n===== {path} [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
