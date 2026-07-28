"""Quick test: install cowsay to verify job success fix."""
import requests, time

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    return r.json()["access_token"]

token = login()
hdrs = {"Authorization": f"Bearer {token}"}

# Clear session
requests.delete(f"{BASE}/api/v1/memory/{ITEM_ID}/session", headers=hdrs)
time.sleep(1)

# Send task
print("Sending: install cowsay...")
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/chat/{ITEM_ID}",
                  json={"message": "帮我安装 cowsay，装完跑 cowsay hello 验证", "history": []},
                  headers=hdrs, timeout=180)
resp = r.json() if "json" in r.headers.get("content-type","") else r.text
print(f"  Status: {r.status_code}, Time: {time.time()-t0:.1f}s")
if isinstance(resp, dict):
    print(f"  Reply: {resp.get('content','')[:200]}")

# Monitor
for i in range(60):
    time.sleep(5)
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs)
    wf = r.json()
    workflows = wf.get("workflows", [])
    active = [w for w in workflows if w.get("status") not in ("completed", "cancelled", "failed", "")]
    
    if not active:
        print(f"\n[{(i+1)*5}s] Done!")
        for w in workflows:
            print(f"  WF {w['workflow_id'][:12]} | status={w['status']}")
            for s in w.get("steps", []):
                print(f"    {s.get('title','')} [{s.get('status')}] attempts={s.get('attempts',0)}")
            for j in w.get("jobs", []):
                print(f"    Job: {j.get('command','')[:60]} [{j.get('status')}] exit={j.get('exit_code')} success={j.get('success')}")
        break
    
    for w in active:
        steps = w.get("steps", [])
        done = sum(1 for s in steps if s.get("status") in ("completed","cancelled","failed"))
        running = [j for j in w.get("jobs",[]) if j.get("status") == "running"]
        print(f"  [{int(time.time()-t0)}s] {w['status']} | {done}/{len(steps)} | {len(running)} running")
else:
    print("TIMEOUT")

# Verify cowsay
import subprocess
result = subprocess.run(["docker", "exec", "termman-daemon-1", "cowsay", "test"],
                       capture_output=True, text=True, timeout=10)
print(f"\ncowsay test: exit={result.returncode}")
if result.returncode == 0:
    print(f"  output: {result.stdout[:100]}")
    print("  [PASS]")
else:
    print(f"  [FAIL] {result.stderr[:100]}")

# Token stats
r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=hdrs)
ts = r.json()
print(f"\nTokens: {ts.get('total_tokens',0)} total, {ts.get('total_turns',0)} turns")