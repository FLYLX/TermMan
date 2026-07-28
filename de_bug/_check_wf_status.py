import requests, json, time

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
    print(f"  objective: {wf.get('objective')}")
    print(f"  report_sent_at: {wf.get('report_sent_at')}")
    steps = wf.get("steps", [])
    for i, s in enumerate(steps):
        ev = (s.get('evidence') or '')[:100]
        print(f"  step {i+1}: [{s.get('status')}] {s.get('title')} | ev={ev}")
    jobs = wf.get("jobs", [])
    print(f"  jobs: {len(jobs)}")
    for j in jobs[-3:]:
        print(f"    [{j.get('status')}] {j.get('command','')[:60]}")

# Also check session history for recent activity
r4 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
hist = r4.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
print(f"\nRecent session msgs: {len(msgs)}")
for m in msgs[-3:]:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:150]
    print(f"  [{role}] {content}")
