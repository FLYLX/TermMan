import requests, time

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    return r.json()["access_token"]

token = login()
hdrs = {"Authorization": f"Bearer {token}"}

for i in range(60):
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs)
    wf = r.json()
    workflows = wf.get("workflows", [])
    active = [w for w in workflows if w.get("status") not in ("completed", "cancelled", "failed", "")]
    
    if not active:
        print(f"[{i*10}s] All workflows terminal!")
        for w in workflows:
            print(f"  WF {w['workflow_id'][:12]} | status={w['status']}")
            print(f"  delivered={w.get('delivered_at')} report_sent={w.get('report_sent_at')}")
            for s in w.get("steps", []):
                print(f"    {s.get('title','')} [{s.get('status')}] attempts={s.get('attempts',0)}")
                if s.get('evidence'):
                    print(f"      evidence: {s['evidence'][:150]}")
        break
    
    for w in active:
        steps = w.get("steps", [])
        done = sum(1 for s in steps if s.get("status") in ("completed","cancelled","failed"))
        running_jobs = [j for j in w.get("jobs",[]) if j.get("status") == "running"]
        print(f"[{i*10}s] WF {w['workflow_id'][:8]} | {w['status']} | {done}/{len(steps)} | {len(running_jobs)} running")
    
    time.sleep(10)
else:
    print("TIMEOUT 600s")

# Check java
import subprocess
result = subprocess.run(["docker", "exec", "termman-daemon-1", "java", "-version"],
                       capture_output=True, text=True, timeout=10)
print(f"\nJava check: exit={result.returncode}")
print(f"  stderr: {result.stderr[:200]}")

# Token stats
r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=hdrs)
ts = r.json()
print(f"\nTokens: {ts.get('total_tokens',0)} total, {ts.get('total_turns',0)} turns")