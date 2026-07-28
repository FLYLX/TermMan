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

print("=== SCENARIO 3: mid-task cancel ===")
# Step 1: start a long install task
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "帮我安装 nginx 和 postgresql，装完验证版本",
    "history": []
}, headers=h, timeout=120)
print(f"Start: {r2.json().get('content','')[:100]}")

# Step 2: wait for a running job to appear
print("Waiting for running job...")
for i in range(10):
    time.sleep(5)
    r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
    jobs = r5.json()
    running = [j for j in jobs.get("jobs", []) if j.get("status") in (None, "running")]
    if running:
        print(f"  Found {len(running)} running job(s) at {i*5}s")
        for j in running:
            print(f"    {j.get('job_id','')} {str(j.get('command',''))[:50]}")
        break

# Step 3: CANCEL!
print("\n--- CANCEL ---")
time.sleep(2)
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "算了不装了，取消吧",
    "history": []
}, headers=h, timeout=60)
print(f"Cancel reply: {r3.json().get('content','')[:200]}")

time.sleep(5)

# Step 4: verify cleanup
print("\n--- VERIFY CLEANUP ---")
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"Workflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"  [{w.get('status')}] {w.get('note', '')[:60]}")

r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {j.get('job_id','')} {str(j.get('command',''))[:50]}")

r3t = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3t.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")