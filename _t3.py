# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check recent session
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=8&offset=0", headers=h, timeout=10)
data = r2.json()
msgs = data.get("messages", [])
for m in msgs:
    mtype = m.get("type", "")
    tool = m.get("tool_name", "")
    content = str(m.get("content", ""))[:150]
    print(f"[{mtype}|{tool}] {content}")
    print("---")

# Check jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {str(j.get('command',''))[:80]}")