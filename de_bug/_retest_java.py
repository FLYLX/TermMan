"""Clean re-test: install Java 21 with fixed job success logic."""
import requests, time, json

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    return r.json()["access_token"]

token = login()
hdrs = {"Authorization": f"Bearer {token}"}

# Check existing workflows
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs)
wf = r.json()
workflows = wf.get("workflows", [])
print(f"Existing workflows: {len(workflows)}")
for w in workflows:
    print(f"  {w['workflow_id'][:12]} | {w['status']} | {w.get('objective','')[:60]}")

# Clear session
print("\nClearing session...")
r = requests.delete(f"{BASE}/api/v1/memory/{ITEM_ID}/session", headers=hdrs)
print(f"  Clear session: {r.status_code}")

# Wait a moment
time.sleep(2)

# Send Java install task
print("\nSending Java install task...")
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/chat/{ITEM_ID}",
                  json={"message": "帮我安装 openjdk-21-jdk-headless，装完跑 java -version 验证", "history": []},
                  headers=hdrs, timeout=180)
elapsed = time.time() - t0
resp = r.json() if "json" in r.headers.get("content-type","") else r.text
print(f"  Status: {r.status_code}, Time: {elapsed:.1f}s")
if isinstance(resp, dict):
    print(f"  Reply: {resp.get('content','')[:200]}")

# Monitor workflow
print("\nMonitoring workflow...")
for i in range(90):
    time.sleep(5)
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs)
    wf = r.json()
    workflows = wf.get("workflows", [])
    active = [w for w in workflows if w.get("status") not in ("completed", "cancelled", "failed", "")]
    
    if not active:
        print(f"\n[{(i+1)*5}s] All workflows terminal!")
        for w in workflows:
            print(f"  WF {w['workflow_id'][:12]} | status={w['status']}")
            print(f"  delivered={w.get('delivered_at')} report_sent={w.get('report_sent_at')}")
            for s in w.get("steps", []):
                print(f"    {s.get('title','')} [{s.get('status')}] attempts={s.get('attempts',0)}")
            for j in w.get("jobs", []):
                print(f"    Job: {j.get('command','')[:60]} [{j.get('status')}] exit={j.get('exit_code')}")
        break
    
    for w in active:
        steps = w.get("steps", [])
        done = sum(1 for s in steps if s.get("status") in ("completed","cancelled","failed"))
        running_jobs = [j for j in w.get("jobs",[]) if j.get("status") == "running"]
        elapsed_total = int(time.time() - t0)
        print(f"  [{elapsed_total}s] {w['status']} | {done}/{len(steps)} steps | {len(running_jobs)} running jobs")
        for j in running_jobs:
            print(f"    running: {j.get('command','')[:80]}")
else:
    print("TIMEOUT after 450s")

# Check java
import subprocess
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "java", "-version"],
                       capture_output=True, text=True, timeout=10)
print(f"\nJava check: exit={result.returncode}")
if result.returncode == 0:
    print(f"  stderr: {result.stderr[:200]}")
    print("  [PASS] Java installed!")
else:
    print(f"  stderr: {result.stderr[:200]}")
    print("  [FAIL] Java not installed")

# Check zombies
result2 = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c", "ps aux | grep -c defunct"],
                        capture_output=True, text=True, timeout=10)
zombie_count = result2.stdout.strip()
print(f"\nZombie processes: {zombie_count}")
if zombie_count == "0" or zombie_count == "1":  # 1 is the grep itself
    print("  [PASS] No zombies")
else:
    print(f"  [WARN] {zombie_count} zombies")

# Token stats
r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=hdrs)
ts = r.json()
print(f"\nToken stats: {ts.get('total_tokens',0)} total, {ts.get('total_turns',0)} turns")
print(f"  Prompt: {ts.get('total_prompt_tokens',0)}, Completion: {ts.get('total_completion_tokens',0)}")

# Check jobs for duplicates
r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=hdrs)
jd = r.json()
jobs = jd.get("jobs", [])
print(f"\nDaemon jobs: {len(jobs)}")
from collections import Counter
commands = [j.get("command", j.get("cmd","")) for j in jobs]
dupes = {c: n for c, n in Counter(commands).items() if n > 1}
if dupes:
    print(f"  [WARN] Duplicates: {dupes}")
else:
    print("  [PASS] No duplicates")