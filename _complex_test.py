import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Start terminal
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
print(f"Terminal: {r.status_code} {r.text[:100]}")
time.sleep(3)

# Baseline
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
baseline = r.json().get("total", 0)
print(f"Baseline: {baseline}")

# Send Java install task
msg = "帮我安装Java 21，装完跑java -version验证一下"
print(f"=== Sending: {msg} ===")
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": msg, "history": []},
    headers=h, timeout=120)
elapsed = time.time() - t0
print(f"Status: {r.status_code} ({elapsed:.1f}s)")
print(f"Response: {r.json().get('content','')[:200]}")