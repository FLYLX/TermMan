import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Get last 8 messages to see the full flow
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=8&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"Total: {total}")
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:300]
    print(f"[{i}] {role}:")
    print(f"    {content}")
    print()