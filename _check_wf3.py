import requests, json

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
print("Status:", r3.status_code)
print("Body:", r3.text[:1000])
