import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Test 3: Terminal command (MC server should be running)
print("=== TEST 3: MC command ===")
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "\u5728MC\u63a7\u5236\u53f0\u6267\u884c list", "history": []}, headers=h, timeout=30)
print(f"  {r3.json().get('content','')[:150]}")

time.sleep(10)

# Check if agent got feedback
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
print("\n  Recent:")
for m in msgs[-3:]:
    print(f"    [{m.get('role')}] {str(m.get('content',''))[:150]}")
