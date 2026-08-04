# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend\app\api\routes\chat.py", encoding="utf-8").read().splitlines()
for start, end in [(745, 920), (1160, 1175), (1680, 1695), (1748, 1760), (1808, 1850), (1944, 1962), (2036, 2046)]:
    print(f"\n--- [{start}-{end}] ---")
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
