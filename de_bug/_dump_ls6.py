# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/services/agent/mcp/local_server.py", encoding="utf-8").read().splitlines()
for i in range(1717, min(1750, len(lines))):
    print(f"{i+1:5}: {lines[i]}")
