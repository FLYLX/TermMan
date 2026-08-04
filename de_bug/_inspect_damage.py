# -*- coding: utf-8 -*-
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
src = open(r"backend\app\api\routes\chat.py", encoding="utf-8").read()
lines = src.splitlines()
hits = [i for i, l in enumerate(lines) if "task_workflow" in l or "PlannedTaskRuntime" in l or "planned_task_runtime" in l]
print("hit lines:", [h+1 for h in hits])
print("\n--- around 695-745 ---")
for i in range(694, min(745, len(lines))):
    print(f"{i+1:5}: {lines[i]}")
