import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Simple chat - should NOT create workflow
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u4eca\u5929\u661f\u671f\u51e0\uff1f", "history": []},
    headers=h)
resp = r2.json()
print(f"Chat 1: {resp.get('content', '')[:200]}")

# Another simple chat
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "1+1\u7b49\u4e8e\u51e0", "history": []},
    headers=h)
resp3 = r3.json()
print(f"Chat 2: {resp3.get('content', '')[:200]}")

# Check no new workflows created
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r4.json()
active_wfs = [w for w in wf_data.get("workflows", []) if w.get("status") not in ("completed", "cancelled")]
print(f"\nActive workflows: {len(active_wfs)}")
for wf in active_wfs:
    print(f"  {wf['workflow_id'][:8]}: {wf.get('status')} - {wf.get('objective','')[:60]}")
