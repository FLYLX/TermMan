import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

print("Waiting 45s for MC startup verification...")
time.sleep(45)

# Workflow
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r.json()
print(f"Workflows: {wf.get('count',0)}")
for w in wf.get("workflows", []):
    print(f"WF: status={w.get('status')}")
    for s in w.get("steps", []):
        ev = s.get('evidence','')[:120]
        print(f"  [{s.get('status'):>10}] {s.get('title','')[:55]}")
        if ev: print(f"             {ev}")

# Session
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
total = r.json().get("total", 0)
print(f"\nSession: {total}")

# Last 3
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
data = r.json()
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:250]}")
    print()

# MC still running?
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
    capture_output=True, text=True)
print(f"MC process: {result.stdout.strip()}")