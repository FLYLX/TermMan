import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

print("=== Stopping MC server ===")
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "把MC服务器停了，输入stop关服", "history": []},
    headers=h, timeout=120)
print(f"Status: {r.status_code}")
print(f"Response: {r.json().get('content','')[:200]}")

time.sleep(25)

import subprocess
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
    capture_output=True, text=True)
print(f"MC process after stop: {result.stdout.strip()}")

r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=2&offset=0", headers=h)
data = r.json()
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for m in msgs[:2]:
    print(f"  {m.get('role')}: {str(m.get('content',''))[:200]}")