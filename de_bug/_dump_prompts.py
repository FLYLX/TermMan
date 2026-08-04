# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/plugins/robot/prompts.py", encoding="utf-8").read().splitlines()
for i in range(234, min(275, len(lines))):
    print(f"{i+1:5}: {lines[i]}")
