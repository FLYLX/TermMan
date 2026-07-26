import requests, json
from app.core.config import settings

BASE = "http://127.0.0.1:8000"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
item_id = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

# Read terminal log
r5 = requests.get(f"{BASE}/api/v1/items/{item_id}/terminal/log", headers=headers, params={"tail": 30})
if r5.status_code == 200:
    data = r5.json()
    log = data.get("log", data.get("content", data.get("lines", "")))
    if isinstance(log, list):
        for line in log[-20:]:
            print(f"  {line}")
    else:
        print(str(log)[-1000:])
else:
    print(f"Terminal log: {r5.status_code}")
    # Try alternate endpoint
    r6 = requests.get(f"{BASE}/api/v1/terminal/{item_id}/log", headers=headers, params={"tail": 20})
    print(f"Alt: {r6.status_code} {r6.text[:500]}")
