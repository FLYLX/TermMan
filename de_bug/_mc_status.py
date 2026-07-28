import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Workflow
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r.json()
for w in wf.get("workflows", []):
    print(f"Workflow: status={w.get('status')}")
    for s in w.get("steps", []):
        print(f"  [{s.get('status'):>10}] {s.get('title','')[:55]} att={s.get('attempts',0)}")

# Jobs
r = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
jobs = r.json()
print(f"\nJobs: {jobs.get('count',0)}")
for j in jobs.get("jobs", []):
    print(f"  {j.get('job_id','?')[:12]} [{j.get('status')}] {str(j.get('command',''))[:100]}")

# Session
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
total = r.json().get("total", 0)
print(f"\nSession: {total}")

# Last 3
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
data = r.json()
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:200]}")
    print()