import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# The test task
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u4e0b\u8f7d\u5b89\u88c5 Java 21\uff0c\u7136\u540e\u7528\u5b83\u542f\u52a8\u5f53\u524d\u76ee\u5f55\u7684 MC 1.20.1 \u670d\u52a1\u5668\uff08server.jar\uff09\uff0c\u542f\u52a8\u6210\u529f\u540e\u544a\u8bc9\u6211", "history": []},
    headers=h)
print(f"Task sent: {r2.status_code} {r2.json().get('content', '')[:150]}")
