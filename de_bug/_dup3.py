# -*- coding: utf-8 -*-
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Start a long job
print("=== Starting sleep 120 ===")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "后台运行 sleep 120",
    "history": []
}, headers=h, timeout=60)
print(f"Reply: {r2.json().get('content','')[:100]}")

time.sleep(5)

# Verify it's running
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  {j.get('job_id','')} elapsed={j.get('elapsed_seconds',0):.0f}s {str(j.get('command',''))[:40]}")

# Now ask for the same
print("\n=== Asking for duplicate sleep 120 ===")
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "再后台运行一个 sleep 120",
    "history": []
}, headers=h, timeout=60)
print(f"Reply: {r3.json().get('content','')[:200]}")

time.sleep(3)
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs after: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  {j.get('job_id','')} elapsed={j.get('elapsed_seconds',0):.0f}s {str(j.get('command',''))[:40]}")