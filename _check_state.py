import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Session history
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=10&offset=0", headers=h)
hist = r5.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
print(f"=== Session ({len(msgs)} msgs) ===")
for m in msgs:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    print(f"  [{role}] {content}")

# Workflows
print("\n=== Workflows ===")
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r3.json()
for wf in wf_data.get("workflows", []):
    print(f"  {wf['workflow_id'][:8]}: status={wf.get('status')} obj={wf.get('objective','')[:80]}")
    for i, s in enumerate(wf.get("steps", [])):
        print(f"    step {i+1}: [{s.get('status')}] {s.get('title')}")
