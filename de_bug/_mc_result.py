import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Workflow
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
for wf in r3.json().get("workflows", []):
    if 'MC' in wf.get('objective','') or wf.get('status') not in ('completed','cancelled'):
        print(f"WF: status={wf.get('status')}")
        for i, s in enumerate(wf.get("steps", [])):
            ev = (s.get('evidence') or '')[:80]
            print(f"  {i+1}. [{s.get('status')}] {s.get('title')} | {ev}")

# Latest
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
print(f"\nLatest:")
for m in msgs[-3:]:
    print(f"  [{m.get('role')}] {str(m.get('content',''))[:200]}")
