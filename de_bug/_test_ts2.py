import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Stop terminal first
print("=== Stopping terminal ===")
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/stop", headers=h)
print(f"Stop: {r.status_code} {r.text[:200]}")
time.sleep(2)

# Start terminal
print("=== Starting terminal ===")
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
print(f"Start: {r.status_code} {r.text[:200]}")
time.sleep(3)

# Write a command to generate output
print("=== Writing echo to terminal ===")
import subprocess
subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "PID=$(ps -eo pid,tty | grep pts | head -1 | awk '{print $1}'); echo 'echo TIMESTAMP_TEST_OK' > /proc/$PID/fd/0"],
    capture_output=True, text=True)

print("Waiting 15s for agent to process...")
time.sleep(15)

# Check session for timestamp prefix
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"Total: {total}")

msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:250]
    has_ts = "[2026-" in content
    print(f"[{i}] role={role} has_timestamp={has_ts}")
    print(f"    {content}")
    print()