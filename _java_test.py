import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Start terminal
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
print(f"Terminal: {r.status_code}")
time.sleep(2)

baseline = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h).json().get("total", 0)
print(f"Baseline: {baseline}")

# Send Java install
msg = "帮我安装Java 17，装完验证java -version"
print(f"\n=== Sending: {msg} ===")
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": msg, "history": []},
    headers=h, timeout=120)
elapsed = time.time() - t0
data = r.json()
content = data.get("content", "")
print(f"HTTP {r.status_code} ({elapsed:.1f}s)")
print(f"Reply: {content[:200]}")

if not content.strip():
    print("!!! EMPTY REPLY !!!")

# Monitor for 3 minutes
last_total = baseline
stuck_count = 0
for check in range(9):
    time.sleep(20)
    
    r2 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
    wf = r2.json()
    wf_info = ""
    for w in wf.get("workflows", []):
        steps = " | ".join([f"{s.get('title','')[:20]}:{s.get('status','')}" for s in w.get("steps", [])])
        wf_info = f"WF={w.get('status')} [{steps}]"
    
    r3 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
    total = r3.json().get("total", 0)
    delta = total - last_total
    
    if delta == 0:
        stuck_count += 1
    else:
        stuck_count = 0
    last_total = total
    
    # Jobs
    r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
    jobs = r4.json()
    active_jobs = len([j for j in jobs.get("jobs", []) if j.get("status") == "running"])
    
    print(f"[{(check+1)*20}s] session={total}(+{delta}) jobs={active_jobs} stuck={stuck_count} {wf_info}")
    
    if stuck_count >= 3:
        print("!!! STUCK for 60s+ !!!")
        # Get last message
        r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=2&offset=0", headers=h)
        d5 = r5.json()
        msgs = d5 if isinstance(d5, list) else d5.get("messages", d5.get("history", []))
        for m in msgs[:2]:
            print(f"  {m.get('role')}: {str(m.get('content',''))[:200]}")
        break
    
    if wf.get("count", 0) == 0 and total > baseline + 3:
        print(">>> Workflow completed <<<")
        break

# Final state
print(f"\n=== Final ===")
r6 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
d6 = r6.json()
total = d6.get("total", 0)
print(f"Session: {total} (was {baseline}, +{total-baseline})")
msgs = d6 if isinstance(d6, list) else d6.get("messages", d6.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:250]}")
    print()