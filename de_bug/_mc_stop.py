import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

baseline = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h).json().get("total", 0)
print(f"Baseline: {baseline}")

# Ask agent to stop MC server
print("=== Sending: stop MC server ===")
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "把MC服务器停了吧，在终端里输入stop命令关服", "history": []},
    headers=h, timeout=120)
print(f"Status: {r.status_code}")
print(f"Response: {r.json().get('content','')[:300]}")

print("\nWaiting 30s for shutdown...")
time.sleep(30)

# Check java process
import subprocess
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "ps aux | grep java | grep -v grep | wc -l"],
    capture_output=True, text=True)
print(f"Java processes: {result.stdout.strip()}")

# Session
after = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h).json().get("total", 0)
print(f"Session: {after} (delta={after-baseline})")

# Last 3
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
data = r.json()
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:200]}")
    print()

# Workflow
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r.json()
print(f"Workflows: {wf.get('count',0)}")
for w in wf.get("workflows", []):
    print(f"  {w.get('workflow_id','?')[:12]} status={w.get('status')}")