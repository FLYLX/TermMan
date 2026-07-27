import requests, json, sys, io, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Baseline
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
baseline = r.json().get("total", 0)
print(f"Baseline: {baseline}")

# Rapid fire 5 web chat messages with 0.3s interval
messages = [
    "echo stress_test_1",
    "echo stress_test_2", 
    "echo stress_test_3",
    "现在几点了？",
    "系统负载怎么样？",
]

print(f"=== Sending {len(messages)} rapid messages ===")
for i, msg in enumerate(messages):
    t0 = time.time()
    r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
        json={"message": msg, "history": []},
        headers=h, timeout=120)
    elapsed = time.time() - t0
    print(f"  [{i+1}] '{msg}' -> {r.status_code} ({elapsed:.1f}s)")
    time.sleep(0.3)

print("\nWaiting 40s for all processing...")
time.sleep(40)

# Check final state
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
final = r.json().get("total", 0)
print(f"\nFinal: {final} (was {baseline}, +{final-baseline})")

# Check last 5 messages
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
data = r.json()
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
print("\n=== Last 5 messages ===")
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:150]
    print(f"[{i}] role={role}: {content}")
    print()

# Verify not stuck - send one more message
print("=== Verifying not stuck ===")
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "你还在吗？回复OK就行", "history": []},
    headers=h, timeout=60)
elapsed = time.time() - t0
print(f"Response: {r.status_code} ({elapsed:.1f}s)")
data = r.json()
print(f"Content: {data.get('content', '')[:200]}")