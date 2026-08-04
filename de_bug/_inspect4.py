# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
src = open(r"backend\app\api\routes\chat.py", encoding="utf-8").read()
lines = src.splitlines()
hits = [i for i, l in enumerate(lines) if "task_workflow" in l]
print("task_workflow hits:", [h+1 for h in hits])
for h in hits:
    for i in range(max(0,h-6), min(len(lines), h+8)):
        print(f"{i+1:5}: {lines[i]}")
idx = src.find("                                    ticket_events")
print("\nticket_events indent hit at char", idx)
idx2 = src.find("if stop_after_final_robot_delivery:")
print("--- stop_after_final region ---")
seg = src[idx2:idx2+300]
print(repr(seg[:300]))
