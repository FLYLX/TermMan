import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Test say command
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u5728MC\u63a7\u5236\u53f0\u53d1\u9001 say hello_from_test", "history": []},
    headers=h)
print(f"Say cmd: {r2.status_code} {r2.json().get('content', '')[:200]}")

time.sleep(10)

r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h)
hist = r5.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
print(f"\nLatest:")
for m in msgs[-3:]:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:300]
    print(f"  [{role}] {content}")
