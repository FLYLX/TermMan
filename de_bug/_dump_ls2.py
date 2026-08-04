# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/services/agent/mcp/local_server.py", 193, 240),
    ("backend/app/services/agent/mcp/local_server.py", 1323, 1400),
    ("backend/app/services/agent/mcp/local_server.py", 1540, 1640),
    ("backend/app/services/agent/mcp/local_server.py", 1740, 1795),
    ("backend/app/services/agent/mcp/local_server.py", 1900, 1930),
    ("backend/app/services/agent/mcp/local_server.py", 2000, 2075),
    ("backend/app/services/agent/mcp/local_server.py", 2160, 2210),
]
for path, start, end in REGIONS:
    print(f"\n===== [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
