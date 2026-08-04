# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
REGIONS = [
    ("backend/app/api/routes/chat.py", 515, 540),
    ("backend/app/api/routes/chat.py", 855, 935),
    ("backend/app/api/routes/chat.py", 1195, 1215),
    ("backend/app/api/routes/chat.py", 1390, 1460),
    ("backend/app/api/routes/chat.py", 1550, 1575),
]
for path, start, end in REGIONS:
    print(f"\n===== {path} [{start}-{end}] =====")
    lines = open(path, encoding="utf-8").read().splitlines()
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
