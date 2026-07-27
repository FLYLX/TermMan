import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

r2 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
data = r2.json()
jobs = data if isinstance(data, list) else data.get("jobs", data.get("data", []))
for j in jobs[-3:]:
    print(f"[{j.get('status')}] elapsed={j.get('elapsed_seconds',0):.0f}s cmd={str(j.get('command',''))[:60]}")
    tail = str(j.get('output_tail', ''))[-300:]
    if tail:
        print(f"  tail: {tail}")
