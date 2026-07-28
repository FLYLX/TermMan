import requests, json, sys, io, time, subprocess
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

# Write to terminal
print("Writing 'echo FLOW_TEST_999' to terminal...")
subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
    "echo 'echo FLOW_TEST_999' > /proc/19/fd/0"],
    capture_output=True, text=True)

print("Waiting 15s...")
time.sleep(15)

r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"After: {total} (was {baseline}, delta={total-baseline})")

msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    print(f"[{i}] role={role}: {content}")
    print()

if total == baseline:
    print("WARNING: Terminal output NOT flowing to agent!")
else:
    print("OK: Terminal output is flowing")