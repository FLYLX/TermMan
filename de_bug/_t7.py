# -*- coding: utf-8 -*-
import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
subprocess.run(["docker", "exec", "TermPaws-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

print("=== COMPLEX TEST: write+run python script ===")
t0 = time.time()
msg = "用python写一个脚本计算斐波那契数列前20项，保存到/tmp/fib.py，然后运行它，把结果告诉我"
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=120)
elapsed = time.time() - t0
d = r2.json()
print(f"  Time: {elapsed:.1f}s")
print(f"  Reply: {d.get('content','')[:200]}")

# Wait for job callbacks
time.sleep(15)

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"\n  Tokens: prompt={td['total_prompt_tokens']}, comp={td['total_completion_tokens']}, turns={td['total_turns']}")
if td['total_completion_tokens'] > 0:
    print(f"  Ratio: {td['total_prompt_tokens']/td['total_completion_tokens']:.1f}:1")
    print(f"  Avg prompt/turn: {td['total_prompt_tokens']/max(td['total_turns'],1):.0f}")

# Check workflow
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"  Workflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"    [{w.get('status')}] {w.get('note', '')[:80]}")
        for s in w.get("steps", []):
            print(f"      [{s.get('status')}] {s.get('title')}")