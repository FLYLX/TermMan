import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=15)
wf = r3.json()
for w in wf.get("workflows", [])[:3]:
    print(f"WF {w['workflow_id'][:8]}: status={w.get('status')} | {str(w.get('objective',''))[:70]}")
    for j in (w.get("jobs") or [])[-6:]:
        print(f"    job[{j.get('status')}] {str(j.get('command',''))[:90]}")
