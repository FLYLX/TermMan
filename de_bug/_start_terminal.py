import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print("login OK")
# start the terminal
r2 = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h, timeout=60)
print(f"start terminal: {r2.status_code} {r2.text[:300]}")
# item status
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}", headers=h, timeout=15)
d = r3.json()
print(f"item status={d.get('status')} socket_connected={d.get('socket_connected')}")
