# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
p = r"de_bug\_busy_merge_test.py"
src = open(p, encoding="utf-8").read()
old = '''for i in range(120):'''
new = '''for i in range(200):'''
assert src.count(old) == 1
src = src.replace(old, new)
old = '''    if el > 40 and stable >= 8:
        print(f"[{el}s] stable 40s -> done monitoring", flush=True)
        break'''
new = '''    if el > 60 and stable >= 12:
        print(f"[{el}s] stable 60s -> done monitoring", flush=True)
        break'''
assert src.count(old) == 1
src = src.replace(old, new)
open(p, "w", encoding="utf-8", newline="\n").write(src)
print("tuned")
