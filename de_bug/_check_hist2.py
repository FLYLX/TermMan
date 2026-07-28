import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Get more history to find the user's original request
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=20&offset=0", headers=h)
hist = r5.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
print(f"=== Session ({len(msgs)} msgs) ===")
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:250]
    print(f"  [{i}][{role}] {content}")
