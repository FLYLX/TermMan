import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Check jobs status
r2 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
data = r2.json()
jobs = data if isinstance(data, list) else data.get("jobs", data.get("data", []))
print(f"Daemon jobs: {len(jobs)}")
for j in jobs[-5:]:
    print(f"  [{j.get('status')}] elapsed={j.get('elapsed_seconds',0):.0f}s cmd={str(j.get('command',''))[:60]}")
    tail = str(j.get('output_tail', ''))[-150:]
    if tail:
        print(f"    tail: {tail}")

# Check workflow
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r3.json()
for wf in wf_data.get("workflows", []):
    if wf.get("status") not in ("completed", "cancelled"):
        print(f"\nWF {wf['workflow_id'][:8]}: status={wf.get('status')}")
        steps = wf.get("steps", [])
        for i, s in enumerate(steps):
            print(f"  step {i+1}: [{s.get('status')}] {s.get('title')}")
