import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

print("Waiting 30s for initial processing...")
time.sleep(30)

# Check workflows
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r.json()
print("=== Workflows ===")
for w in wf.get("workflows", []):
    print(f"  id={w.get('workflow_id','?')[:12]} status={w.get('status')} title={w.get('title','')[:60]}")
    for s in w.get("steps", []):
        print(f"    step {s.get('step_number')}: [{s.get('status')}] {s.get('title','')[:50]} attempts={s.get('attempts',0)}")

# Check jobs
r = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
jobs = r.json()
print(f"\n=== Jobs ({jobs.get('count',0)}) ===")
for j in jobs.get("jobs", []):
    print(f"  id={j.get('job_id','?')[:12]} status={j.get('status')} cmd={str(j.get('command',''))[:80]}")

# Check session
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"\n=== Session: {total} messages ===")
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    print(f"[{i}] role={role}: {content}")
    print()