import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

time.sleep(20)

# Workflow final state
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r.json()
print(f"Workflows: {wf.get('count',0)}")
for w in wf.get("workflows", []):
    print(f"  status={w.get('status')} delivered={w.get('delivered_at')}")

# Last 3 messages
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"Session: {total}")
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:300]}")
    print()