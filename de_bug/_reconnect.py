import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check item status
r2 = requests.get(f"{BASE}/api/v1/items/{ITEM}", headers=h)
item = r2.json()
print(f"Item status: {item.get('status')}")

# Try to start/reconnect terminal
r3 = requests.post(f"{BASE}/api/v1/items/{ITEM}/terminal/start", headers=h)
print(f"Terminal start: {r3.status_code} {r3.text[:100]}")
