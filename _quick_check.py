import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
h = {"Authorization": f"Bearer {r.json()['access_token']}"}
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h)
d = r.json()
print(f"Total: {d.get('total',0)}")
msgs = d if isinstance(d, list) else d.get("messages", d.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:200]}")
    print()
# Workflow
r2 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r2.json()
for w in wf.get("workflows", []):
    print(f"WF: {w.get('status')}")
    for s in w.get("steps", []):
        print(f"  [{s.get('status')}] {s.get('title','')[:50]}")