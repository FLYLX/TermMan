# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

# Use a novel task not in history
print("=== S1 NOVEL TASK: install wget + tree ===")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "帮我安装 wget 和 tree，装完验证版本",
    "history": []
}, headers=h, timeout=120)
print(f"Reply: {r2.json().get('content','')[:200]}")

time.sleep(25)

r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"\nWorkflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"  [{w.get('status')}] note={w.get('note', '')[:80]}")
        for s in w.get("steps", []):
            print(f"    [{s.get('status')}] {s.get('title')} att={s.get('attempts',0)}")
else:
    print("  STILL NO WORKFLOW!")

r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','running')}] {j.get('job_id','')} cmd={str(j.get('command',''))[:60]}")

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")

# Check thinking
r2s = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h, timeout=10)
msgs = r2s.json().get("messages", [])
for m in msgs:
    if m.get("type") == "agent_thinking":
        print(f"\nThinking: {str(m.get('content',''))[:300]}")