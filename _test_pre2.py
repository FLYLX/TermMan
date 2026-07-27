import requests, json

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Full workflow details
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r3.json()
for wf in wf_data.get("workflows", []):
    print(f"WF: {wf['workflow_id']}")
    print(f"  status: {wf.get('status')}")
    print(f"  objective: {wf.get('objective')}")
    print(f"  queue_status: {wf.get('queue_status')}")
    steps = wf.get("steps", [])
    for i, s in enumerate(steps):
        print(f"  step {i+1}: [{s.get('status')}] {s.get('title')}")
    print()

# Check daemon connection
r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}", headers=h)
item_data = r4.json()
print(f"Item status: {item_data.get('status')}")
print(f"Daemon: {item_data.get('daemon_status', 'unknown')}")
