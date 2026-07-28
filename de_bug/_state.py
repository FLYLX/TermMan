import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check current state
r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
print(f"Tokens: {data.get('total_tokens',0)} total, {data.get('total_turns',0)} turns")

r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
for wf in r3.json().get("workflows", []):
    print(f"WF: status={wf.get('status')} obj={wf.get('objective','')[:60]}")
    for i, s in enumerate(wf.get("steps", [])):
        print(f"  {i+1}. [{s.get('status')}] {s.get('title')}")

# Check last session msg
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
for m in msgs[-2:]:
    print(f"  [{m.get('role')}] {str(m.get('content',''))[:150]}")
