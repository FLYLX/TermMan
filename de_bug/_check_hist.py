import requests, json

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

r4 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=10&offset=0", headers=h)
hist = r4.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
print(f"Session msgs: {len(msgs)}")
for m in msgs:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    print(f"\n[{role}] {content}")
