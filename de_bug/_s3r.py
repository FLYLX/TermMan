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

print("=== S3 RETRY: slow task + cancel ===")
# Use a task with sleep to guarantee time to cancel
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "后台运行 sleep 120 然后 echo done，再后台运行 sleep 120 然后 echo done2",
    "history": []
}, headers=h, timeout=120)
print(f"Start: {r2.json().get('content','')[:100]}")

# Wait for jobs
time.sleep(8)
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs before cancel: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  {j.get('job_id','')} {str(j.get('command',''))[:50]}")

# CANCEL
print("\n--- CANCEL ---")
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "停！全部取消不做了",
    "history": []
}, headers=h, timeout=60)
print(f"Cancel reply: {r3.json().get('content','')[:200]}")

time.sleep(5)

# Verify
print("\n--- VERIFY ---")
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs after: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {j.get('job_id','')} {str(j.get('command',''))[:50]}")

r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"Workflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"  [{w.get('status')}]")

r3t = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3t.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")

# Step 5: verify chat after cancel doesn't trigger workflow
print("\n--- POST-CANCEL CHAT ---")
r6 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "1+1等于",
    "history": []
}, headers=h, timeout=60)
print(f"Chat: {r6.json().get('content','')[:100]}")

r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
print(f"Workflows after chat: {r4.json().get('count', 0)}")