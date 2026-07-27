import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check filter rules
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
baseline = r.json().get("total", 0)
print(f"Baseline: {baseline}")

# Send a nudge to the terminal to unstick the agent
print("Sending 'echo MC_CHECK' to terminal to trigger agent...")
subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
    "echo 'echo MC_SERVER_CHECK' > /proc/19/fd/0"],
    capture_output=True, text=True)

time.sleep(20)

r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"After: {total} (delta={total-baseline})")

msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:250]
    print(f"[{i}] {role}: {content}")
    print()