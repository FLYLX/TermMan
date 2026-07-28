import requests, time

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    return r.json()["access_token"]

def hdrs(t):
    return {"Authorization": f"Bearer {t}"}

token = login()

for i in range(60):
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs(token))
    wf = r.json()
    workflows = wf.get("workflows", [])
    
    # Check for any non-terminal workflow
    active = [w for w in workflows if w.get("status") not in ("completed", "cancelled", "failed", "")]
    
    if not active:
        print(f"[{i*5}s] All workflows terminal")
        for w in workflows:
            print(f"  WF {w['workflow_id'][:12]} | status={w['status']}")
            print(f"  delivered={w.get('delivered_at')} report_sent={w.get('report_sent_at')}")
            for s in w.get("steps", []):
                print(f"    {s.get('title','')} [{s.get('status')}] attempts={s.get('attempts',0)}")
        break
    
    for w in active:
        steps = w.get("steps", [])
        done = sum(1 for s in steps if s.get("status") in ("completed","cancelled","failed"))
        running_jobs = [j for j in w.get("jobs",[]) if j.get("status") == "running"]
        print(f"[{i*5}s] WF {w['workflow_id'][:8]} | status={w['status']} | {done}/{len(steps)} steps | {len(running_jobs)} running")
        for s in steps:
            if s.get("status") in ("running", "waiting"):
                print(f"    -> {s.get('title','')} [{s.get('status')}]")
        for j in running_jobs:
            print(f"    job: {j.get('command','')[:80]}")
    
    time.sleep(5)
else:
    print("TIMEOUT after 300s")
    # Print final state
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs(token))
    for w in r.json().get("workflows", []):
        print(f"  WF {w['workflow_id'][:12]} | status={w['status']}")
        for s in w.get("steps", []):
            print(f"    {s.get('title','')} [{s.get('status')}]")

# Final check
print("\n--- Final daemon jobs ---")
r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=hdrs(token))
for j in r.json().get("jobs", []):
    jid = j.get("job_id", j.get("id", ""))
    cmd = j.get("command", j.get("cmd", ""))
    st = j.get("status", "")
    print(f"  {jid[:12] if jid else '??'} | {st} | {cmd[:80]}")

# Check java
print("\n--- Java check ---")
import subprocess
result = subprocess.run(["docker", "exec", "termman-daemon-1", "java", "-version"],
                       capture_output=True, text=True, timeout=10)
print(f"  stdout: {result.stdout[:200]}")
print(f"  stderr: {result.stderr[:200]}")
print(f"  exit: {result.returncode}")