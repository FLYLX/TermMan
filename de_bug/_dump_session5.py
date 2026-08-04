# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/services/agent/session.py", encoding="utf-8").read().splitlines()
for start, end in [(1110, 1124), (3296, 3326)]:
    print(f"\n===== [{start}-{end}] =====")
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
hits = [n+1 for n, l in enumerate(lines) if "delivery_is_final" in l]
print("\ndelivery_is_final lines:", hits)
