import requests, json, time
from app.core.config import settings

BASE = "http://127.0.0.1:8000"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
item_id = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

# Try restart instead of start
r2 = requests.post(f"{BASE}/api/v1/items/{item_id}/restart", headers=headers)
print(f"Restart: {r2.status_code} {r2.text[:200]}")

time.sleep(5)

# Verify terminal works
r3 = requests.post(f"{BASE}/api/v1/chat/{item_id}", headers=headers,
                   json={"message": "\u8dd1\u4e2a echo ok", "history": []}, timeout=60)
print(f"Chat: {r3.status_code}")

time.sleep(10)
r4 = requests.get(f"{BASE}/api/v1/memory/{item_id}/session", headers=headers, params={"limit": 3, "offset": 0})
data = r4.json()
msgs = data if isinstance(data, list) else data.get("messages", data.get("items", []))
for m in msgs[:2]:
    role = m.get("role","")
    c = str(m.get("content",""))[:200]
    print(f"  [{role}] {c}")
