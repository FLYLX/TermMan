import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Check workflow
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r3.json()
for wf in wf_data.get("workflows", []):
    print(f"WF {wf['workflow_id'][:8]}: status={wf.get('status')}")
    print(f"  report_sent_at: {wf.get('report_sent_at')}")
    steps = wf.get("steps", [])
    for i, s in enumerate(steps):
        ev = (s.get('evidence') or '')[:80]
        print(f"  step {i+1}: [{s.get('status')}] {s.get('title')} | ev={ev}")

# Check jobs
r2 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
data = r2.json()
jobs = data if isinstance(data, list) else data.get("jobs", data.get("data", []))
for j in jobs[-3:]:
    print(f"  job: [{j.get('status')}] elapsed={j.get('elapsed_seconds',0):.0f}s cmd={str(j.get('command',''))[:60]}")

# Latest session
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=2&offset=0", headers=h)
hist = r5.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
for m in msgs[-1:]:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:300]
    print(f"\n  [{role}] {content}")
