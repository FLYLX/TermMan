import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# TEST A: Complex multi-step with potential failure
print("=== TEST A: Install nginx + configure + verify ===")
rA = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "\u5e2e\u6211\u88c5\u4e2a redis-server\uff0c\u88c5\u5b8c\u542f\u52a8\u5b83\uff0c\u7136\u540e\u7528 redis-cli ping \u9a8c\u8bc1\u80fd\u901a", "history": []},
    headers=h, timeout=30)
print(f"  Sent: {rA.json().get('content','')[:100]}")

print("\nWaiting 45s...")
time.sleep(45)

# Check workflow A
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
for wf in r3.json().get("workflows", []):
    if wf.get('status') not in ('completed', 'cancelled'):
        print(f"  WF: status={wf.get('status')} obj={wf.get('objective','')[:60]}")
        for i, s in enumerate(wf.get("steps", [])):
            print(f"    {i+1}. [{s.get('status')}] {s.get('title')}")

# TEST B: Mid-task interruption
print("\n=== TEST B: Interrupt with new instruction ===")
rB = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "\u7b97\u4e86\u4e0d\u88c5redis\u4e86\uff0c\u5e2e\u6211\u67e5\u4e00\u4e0b\u5f53\u524d\u670d\u52a1\u5668\u5185\u5b58\u7528\u4e86\u591a\u5c11", "history": []},
    headers=h, timeout=30)
print(f"  Sent: {rB.json().get('content','')[:100]}")

time.sleep(15)

# Check if old workflow was cancelled
r3b = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
print("\n  Workflows after interrupt:")
for wf in r3b.json().get("workflows", []):
    print(f"    {wf.get('status')}: {wf.get('objective','')[:50]}")

# Check session for response
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
print("\n  Latest:")
for m in msgs[-2:]:
    print(f"    [{m.get('role')}] {str(m.get('content',''))[:200]}")
