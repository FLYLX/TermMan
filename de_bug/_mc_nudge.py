import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check current state
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
before = r.json().get("total", 0)
print(f"Before nudge: {before}")

# Send nudge via web chat
print("Sending nudge...")
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "MC服务器启动好了吗？看看终端输出，如果Done了就完成workflow步骤", "history": []},
    headers=h, timeout=120)
print(f"Nudge response: {r.status_code} {r.json().get('content','')[:200]}")

time.sleep(15)

# Check after
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
after = r.json().get("total", 0)
print(f"After: {after} (delta={after-before})")

# Workflow
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r.json()
for w in wf.get("workflows", []):
    print(f"WF: status={w.get('status')}")
    for s in w.get("steps", []):
        print(f"  [{s.get('status'):>10}] {s.get('title','')[:55]}")

# Last 3
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
data = r.json()
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:200]}")
    print()