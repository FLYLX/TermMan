import requests, json, time

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Cancel old workflow via web chat
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u53d6\u6d88\u5f53\u524d\u6240\u6709\u4efb\u52a1", "history": []},
    headers=h)
print("Cancel msg:", r2.status_code, r2.text[:300])

time.sleep(8)

# Check workflow status
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r3.json()
for wf in wf_data.get("workflows", []):
    print(f"WF {wf['workflow_id'][:8]}: status={wf.get('status')}")
