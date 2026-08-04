# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/services/agent/mcp/local_server.py", encoding="utf-8").read().splitlines()
for start, end in [(1642, 1665), (1690, 1715)]:
    print(f"\n===== [{start}-{end}] =====")
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
