import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# TEST C: Task that will fail and need recovery
print("=== TEST C: Install package that doesn't exist ===")
rC = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "\u5e2e\u6211\u88c5\u4e2a nonexistent-package-xyz-12345", "history": []},
    headers=h, timeout=30)
print(f"  Sent: {rC.json().get('content','')[:100]}")

print("Waiting 30s...")
time.sleep(30)

# Check how agent handled the failure
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
print("\n  Session:")
for m in msgs[-4:]:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    print(f"    [{role}] {content}")

# TEST D: Multi-tool sequence
print("\n=== TEST D: Write file + read it back ===")
rD = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "\u5728\u5f53\u524d\u76ee\u5f55\u521b\u5efa\u4e00\u4e2a hello.txt \u5199\u5165 hello world\uff0c\u7136\u540e cat \u51fa\u6765\u7ed9\u6211\u770b", "history": []},
    headers=h, timeout=30)
print(f"  Sent: {rD.json().get('content','')[:100]}")

time.sleep(15)

r5d = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
msgs = r5d.json() if isinstance(r5d.json(), list) else r5d.json().get("messages", [])
print("\n  Latest:")
for m in msgs[-2:]:
    print(f"    [{m.get('role')}] {str(m.get('content',''))[:200]}")
