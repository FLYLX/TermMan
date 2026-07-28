# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

print("=== INTERRUPT TEST ===")
# Start a long task
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "后台运行 sleep 60，然后再后台运行 echo done_after_sleep",
    "history": []
}, headers=h, timeout=60)
print(f"Start: {r2.json().get('content','')[:100]}")

# Wait for first job to start
time.sleep(5)

# Check jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs before interrupt: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  {j.get('job_id','')} {str(j.get('command',''))[:40]}")

# Interrupt!
print("\n--- SENDING INTERRUPT ---")
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "停！取消所有后台任务，不要做了",
    "history": []
}, headers=h, timeout=60)
print(f"Interrupt reply: {r3.json().get('content','')[:200]}")

time.sleep(3)

# Check cleanup
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs after interrupt: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {j.get('job_id','')} {str(j.get('command',''))[:40]}")

# Tokens
r3t = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3t.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")