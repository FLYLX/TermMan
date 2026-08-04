# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/api/routes/chat.py", 1735, 1760),
    ("backend/app/api/routes/chat.py", 1895, 1915),
    ("backend/app/api/routes/chat.py", 2060, 2140),
    ("backend/app/api/routes/chat.py", 2195, 2230),
    ("backend/app/api/routes/chat.py", 2310, 2335),
    ("backend/app/api/routes/chat.py", 1165, 1195),
    ("backend/app/api/routes/chat.py", 1280, 1300),
]
for path, start, end in REGIONS:
    print(f"\n===== {path} [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
