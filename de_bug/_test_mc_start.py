import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# First check what's in the workdir
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u770b\u770b\u5f53\u524d\u76ee\u5f55\u6709\u6ca1\u6709 server.jar\uff0c\u6709\u7684\u8bdd\u76f4\u63a5\u7528 java -jar server.jar nogui \u542f\u52a8MC\u670d\u52a1\u5668", "history": []},
    headers=h)
print(f"Start MC: {r2.status_code} {r2.json().get('content', '')[:200]}")
