# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/services/agent/reply_ticket.py", 641, 700),
    ("backend/app/services/agent/mcp/local_server.py", 145, 205),
    ("backend/app/services/agent/session.py", 2000, 2050),
    ("backend/app/services/agent/tool_selection.py", 18, 45),
]
for path, start, end in REGIONS:
    print(f"\n===== {path} [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
