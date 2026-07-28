import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "\u5b89\u88c5java21", "history": []}, headers=h, timeout=60)
print(f"{r2.status_code}: {r2.json().get('content','')[:80]}")
