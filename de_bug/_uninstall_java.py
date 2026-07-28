import requests, json, time

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Uninstall all java first
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u628a\u6240\u6709 Java \u90fd\u5378\u8f7d\u6389\uff0c\u5305\u62ec Corretto 17 \u548c Corretto 21\uff0c\u5220\u5e72\u51c0", "history": []},
    headers=h)
print("Uninstall:", r2.status_code, r2.json().get("content", "")[:200])

print("\nWaiting 25s for uninstall to complete...")
time.sleep(25)

# Check session
r4 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
hist = r4.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
for m in msgs[-2:]:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    print(f"[{role}] {content}")
