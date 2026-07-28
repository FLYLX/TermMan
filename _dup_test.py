# -*- coding: utf-8 -*-
import requests, json, sys, io, time, subprocess
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

# Test: ask agent to run sleep 30 twice
print("=== TEST: duplicate job detection ===")
msg = "后台运行 sleep 30，然后立刻再后台运行一个一模一样的 sleep 30"
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=90)
d = r2.json()
print(f"Reply: {d.get('content','')[:300]}")

time.sleep(3)

# Check jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {j.get('job_id','')} {str(j.get('command',''))[:60]}")

# Tokens
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"\nTokens: prompt={td['total_prompt_tokens']}, comp={td['total_completion_tokens']}, turns={td['total_turns']}")