# -*- coding: utf-8 -*-
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Wait for sleep 30 to still be running, then ask for the same
print("Waiting 5s for first job to still be running...")
time.sleep(5)

# Check current jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Current jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  {j.get('job_id','')} {str(j.get('command',''))[:40]}")

# Now ask for the same command
print("\n=== Asking for duplicate sleep 30 ===")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "再后台运行一个 sleep 30",
    "history": []
}, headers=h, timeout=60)
d = r2.json()
print(f"Reply: {d.get('content','')[:300]}")

time.sleep(3)
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs after: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  {j.get('job_id','')} {str(j.get('command',''))[:40]}")