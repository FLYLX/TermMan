import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Start terminal
print("=== Starting terminal ===")
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
print(f"Start: {r.status_code} {r.text[:200]}")
time.sleep(3)

# Check session baseline
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
baseline = r.json().get("total", 0)
print(f"Baseline: {baseline}")

print("Waiting 15s for terminal output to trigger agent...")
time.sleep(15)

# Check if terminal output has timestamp prefix
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"Total: {total} (was {baseline})")

msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    print(f"[{i}] role={role}: {content}")
    print()