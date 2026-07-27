import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r2 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
print(f"Status: {r2.status_code}")
print(json.dumps(r2.json(), indent=2, ensure_ascii=False)[:500])
