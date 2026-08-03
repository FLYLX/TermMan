import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=8&offset=0", headers=h, timeout=15)
j = r5.json()
msgs = j if isinstance(j, list) else j.get("messages", [])
print("recent %d msgs:" % len(msgs))
for m in msgs:
    role = m.get("role"); c = str(m.get("content", ""))
    print(f"  [{role}] {c[:300]}")
