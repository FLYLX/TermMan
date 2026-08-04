import requests, json, time, re
from app.core.config import settings

BASE = "http://127.0.0.1:8000"
r0 = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r0.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
item_id = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def web_send(text):
    return requests.post(f"{BASE}/api/v1/chat/{item_id}", headers=headers,
                         json={"message": text, "history": []}, timeout=300)

def get_msgs(limit=10):
    r4 = requests.get(f"{BASE}/api/v1/memory/{item_id}/session", headers=headers, params={"limit": limit, "offset": 0})
    data = r4.json()
    return data if isinstance(data, list) else data.get("messages", data.get("items", []))

# Test 1: Simple chat (no workflow)
print("[T1] 简单聊天")
web_send("\u4f60\u597d\u5440")
time.sleep(6)
msgs = get_msgs(3)
for m in msgs[:2]:
    c = str(m.get("content",""))[:100]
    if m.get("role") == "assistant" and len(c) > 5:
        print(f"  -> {c}")
        break

# Test 2: Multi-step task (should create workflow)
print("\n[T2] 安装任务（应建 workflow）")
web_send("\u5e2e\u6211\u5b89\u88c5 libcurl4-openssl-dev\uff0c\u88c5\u5b8c\u786e\u8ba4 dpkg -l | grep libcurl")
time.sleep(20)
msgs = get_msgs(8)
wf_created = any("Task workflow updated: created" in str(m.get("content","")) or 
                 "Task workflow updated: active" in str(m.get("content","")) for m in msgs)
print(f"  Workflow created: {wf_created}")
# Show latest
for m in msgs[:2]:
    c = str(m.get("content",""))[:150]
    if m.get("role") == "assistant" and len(c) > 10:
        print(f"  -> {c}")

# Test 3: Wait for completion
print("\n[T3] 等待完成...")
time.sleep(15)
msgs = get_msgs(4)
for m in msgs[:3]:
    c = str(m.get("content",""))[:200]
    role = m.get("role","")
    if "ready_to_report" in c or "completed" in c:
        print(f"  -> DONE: {c[:100]}")
    elif role == "assistant" and len(c) > 20 and "Executing" not in c:
        print(f"  -> [{role}] {c[:150]}")

# Test 4: Another task immediately
print("\n[T4] 紧接着新任务")
web_send("\u518d\u5e2e\u6211\u88c5\u4e2a libssl-dev\uff0c\u88c5\u5b8c\u786e\u8ba4\u4e00\u4e0b")
time.sleep(20)
msgs = get_msgs(5)
wf_count = sum(1 for m in msgs if "Task workflow updated:" in str(m.get("content","")))
print(f"  Workflow updates in window: {wf_count}")
for m in msgs[:2]:
    c = str(m.get("content",""))[:150]
    if m.get("role") == "assistant" and len(c) > 10:
        print(f"  -> {c}")

# Final check
print("\n[FINAL]")
r3 = requests.get(f"{BASE}/api/v1/items/{item_id}/jobs", headers=headers, params={"status": "running"})
data = r3.json()
jobs = data.get("jobs", []) if isinstance(data, dict) else data
print(f"  Running jobs: {len(jobs)}")
msgs = get_msgs(2)
for m in msgs[:1]:
    print(f"  Last: [{m.get('role','')}] {str(m.get('content',''))[:200]}")
