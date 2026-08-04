# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REGIONS = [
    ("backend/app/services/agent/task_workflow.py", 1281, 1360),
    ("backend/app/services/agent/task_workflow.py", 558, 615),
    ("backend/app/api/routes/chat.py", 515, 540),
    ("backend/app/api/routes/chat.py", 855, 930),
    ("backend/app/api/routes/chat.py", 1195, 1215),
    ("backend/app/api/routes/chat.py", 1390, 1460),
    ("backend/app/api/routes/chat.py", 1550, 1575),
    ("backend/app/api/routes/chat.py", 1735, 1760),
    ("backend/app/api/routes/chat.py", 1895, 1915),
    ("backend/app/api/routes/chat.py", 2060, 2140),
    ("backend/app/api/routes/chat.py", 2195, 2230),
    ("backend/app/api/routes/chat.py", 2310, 2335),
    ("backend/app/services/agent/mcp/local_server.py", 100, 145),
    ("backend/app/services/agent/mcp/local_server.py", 1115, 1165),
    ("backend/app/plugins/robot/agent/integration.py", 150, 180),
    ("backend/app/api/routes/utils.py", 75, 100),
]
for path, start, end in REGIONS:
    print(f"\n===== {path} [{start}-{end}] =====")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
        for i in range(start-1, min(end, len(lines))):
            print(f"{i+1:5}: {lines[i]}")
    except Exception as e:
        print("ERR", e)
