# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

print("=== RAPID FIRE TEST (3 messages in 1s) ===")

def send(msg, idx):
    try:
        r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=60)
        d = r2.json()
        print(f"  [{idx}] {msg} -> {d.get('content','')[:80]}")
    except Exception as e:
        print(f"  [{idx}] {msg} -> ERROR: {e}")

# Send 3 messages rapidly
threads = []
msgs = ["echo hello_1", "echo hello_2", "echo hello_3"]
for i, m in enumerate(msgs):
    t = threading.Thread(target=send, args=(m, i))
    threads.append(t)
    t.start()
    time.sleep(0.3)  # 300ms apart

for t in threads:
    t.join(timeout=90)

time.sleep(10)

# Check results
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {str(j.get('command',''))[:50]}")

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")

# Check for duplicate responses
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=15&offset=0", headers=h, timeout=10)
msgs = r2.json().get("messages", [])
responses = [m for m in msgs if m.get("type") == "agent_response"]
print(f"Agent responses: {len(responses)}")
for m in responses:
    print(f"  {str(m.get('content',''))[:120]}")