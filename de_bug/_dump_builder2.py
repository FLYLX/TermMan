# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/services/agent/prompts/builder.py", encoding="utf-8").read().splitlines()
for start, end in [(893, 912), (1023, 1042)]:
    print(f"\n===== [{start}-{end}] =====")
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
