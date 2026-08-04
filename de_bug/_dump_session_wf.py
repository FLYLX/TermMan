# -*- coding: utf-8 -*-
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/services/agent/session.py", encoding="utf-8").read().splitlines()
hits = [i for i, l in enumerate(lines) if "task_workflow" in l]
shown = set()
for h in hits:
    start, end = max(0, h-7), min(len(lines), h+9)
    if any(i in shown for i in range(start, end)):
        end2 = end
    print(f"\n--- around {h+1} ---")
    for i in range(start, end):
        shown.add(i)
        print(f"{i+1:5}: {lines[i]}")
