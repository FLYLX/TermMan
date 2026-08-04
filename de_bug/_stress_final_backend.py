import requests, json, time, re, threading
from app.core.config import settings
from collections import Counter

BASE = "http://127.0.0.1:8000"
secret = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY
robot_id = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"

r0 = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r0.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
item_id = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def qq_send(text):
    payload = {
        "sender_key": "private_2537134688",
        "text": text,
        "reply_target": {
            "target_type": "private",
            "target_id": "2537134688",
            "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"}
        }
    }
    return requests.post(f"{BASE}/api/v1/robots/{robot_id}/dispatch", json=payload,
                         headers={"X-Termman-Bridge-Token": secret}, timeout=90)

def web_send(text):
    return requests.post(f"{BASE}/api/v1/chat/{item_id}", headers=headers,
                         json={"message": text, "history": []}, timeout=300)

def get_msgs(limit=30):
    r4 = requests.get(f"{BASE}/api/v1/memory/{item_id}/session", headers=headers, params={"limit": limit, "offset": 0})
    data = r4.json()
    return data if isinstance(data, list) else data.get("messages", data.get("items", []))

def get_running_jobs():
    r3 = requests.get(f"{BASE}/api/v1/items/{item_id}/jobs", headers=headers, params={"status": "running"})
    data = r3.json()
    return data.get("jobs", []) if isinstance(data, dict) else data

print("=" * 60)
print("STRESS TEST: Complex install + interrupt + cancel + new task")
print("=" * 60)

# Phase 1: QQ complex task
print("\n[P1] QQ: 安装 Python 3.12 从源码编译")
qq_send("\u5e2e\u6211\u4ece\u6e90\u7801\u7f16\u8bd1\u5b89\u88c5 Python 3.12\uff0c\u88c5\u5b8c\u9a8c\u8bc1 python3.12 --version")
time.sleep(20)
jobs = get_running_jobs()
print(f"  Running jobs: {len(jobs)}")

# Phase 2: Web interrupt (casual)
print("\n[P2] Web: 闲聊打断")
web_send("\u4eca\u5929\u661f\u671f\u51e0")
time.sleep(8)

# Phase 3: QQ cancel
print("\n[P3] QQ: 取消")
qq_send("\u7b97\u4e86\u4e0d\u88c5\u4e86\uff0c\u53d6\u6d88\u5427")
time.sleep(15)

# Phase 4: Immediately new task
print("\n[P4] Web: 新任务 安装 sl")
web_send("\u5e2e\u6211\u88c5\u4e2a fortune\uff0c\u88c5\u5b8c\u8dd1\u4e00\u4e0b fortune")
time.sleep(20)

# Phase 5: Check final state
print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)

jobs_final = get_running_jobs()
print(f"\nRunning jobs: {len(jobs_final)}")
for j in jobs_final:
    if isinstance(j, dict):
        print(f"  ORPHAN: {j.get('command','')[:60]}")

msgs = get_msgs(30)

# Extract all job commands
all_jobs = []
for m in msgs:
    content = str(m.get("content", ""))
    if m.get("role") == "terminal" and "command:" in content:
        cmds = re.findall(r"command: (.+)", content)
        all_jobs.extend(c.strip()[:60] for c in cmds)

dupes = {k: v for k, v in Counter(all_jobs).items() if v > 1}
print(f"\nTotal jobs in history: {len(all_jobs)}")
print(f"Duplicates: {dupes if dupes else 'None'}")

# Check for stuck/zombie
stuck = [m for m in msgs if "\u4efb\u52a1\u672a\u80fd\u5b8c\u6210" in str(m.get("content", ""))]
not_linked = [m for m in msgs if "No authoritative" in str(m.get("content", ""))]
print(f"\nStuck messages: {len(stuck)}")
print(f"'Not linked' errors: {len(not_linked)}")

# Check workflow states
wf_states = []
for m in msgs:
    content = str(m.get("content", ""))
    if "Task workflow updated:" in content:
        state = content.split("Task workflow updated:")[1].split("\n")[0].strip()
        wf_states.append(state)
print(f"\nWorkflow transitions: {wf_states[-8:]}")

# Final response
last_resp = ""
for m in msgs:
    if m.get("role") == "assistant":
        c = str(m.get("content", ""))
        if len(c) > 20 and "Task workflow" not in c and "Executing" not in c and "Recorded" not in c:
            last_resp = c[:200]
print(f"\nLast response: {last_resp}")

# Verdict
print("\n" + "=" * 60)
issues = []
if jobs_final: issues.append(f"{len(jobs_final)} orphan jobs")
if stuck: issues.append(f"{len(stuck)} stuck msgs")
if dupes: issues.append(f"duplicate jobs: {dupes}")
if issues:
    print(f"[ISSUES] {'; '.join(issues)}")
else:
    print("[PASS] No orphans, no zombies, no duplicates, no stuck")
print("=" * 60)
