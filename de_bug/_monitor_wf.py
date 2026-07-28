"""Monitor workflow until completion, then analyze."""
import requests, time, json

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    return r.json()["access_token"]

def hdrs(t):
    return {"Authorization": f"Bearer {t}"}

token = login()

# Monitor
for i in range(60):
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs(token))
    wf = r.json()
    workflows = wf.get("workflows", [])
    active = [w for w in workflows if w.get("status") in ("running","pending","waiting_job")]
    
    if not active:
        print(f"[{i*5}s] No active workflows - done!")
        # Print final state of all workflows
        for w in workflows:
            print(f"\n  WF {w['workflow_id'][:12]} | status={w['status']} | title={w.get('objective','')[:80]}")
            print(f"  source: {w.get('source_type')} / {w.get('source_label')}")
            print(f"  tickets: {w.get('reply_ticket_ids', [])}")
            print(f"  delivered: {w.get('delivered_at')}")
            print(f"  report_sent: {w.get('report_sent_at')}")
            for s in w.get("steps", []):
                print(f"    Step {s.get('step_id','')[:8]}: {s.get('title','')} [{s.get('status')}] attempts={s.get('attempts',0)}")
                if s.get('evidence'):
                    print(f"      evidence: {s['evidence'][:120]}")
            for j in w.get("jobs", []):
                print(f"    Job {j.get('workflow_job_id','')[:8]}: {j.get('command','')[:60]} [{j.get('status')}] step={j.get('step_id','')[:8]}")
        break
    
    for w in active:
        steps = w.get("steps", [])
        done = sum(1 for s in steps if s.get("status") in ("completed","cancelled","failed"))
        running_jobs = [j for j in w.get("jobs",[]) if j.get("status") == "running"]
        print(f"[{i*5}s] WF {w['workflow_id'][:8]} | {w['status']} | {done}/{len(steps)} steps | {len(running_jobs)} running jobs")
        for j in running_jobs:
            print(f"    running: {j.get('command','')[:80]}")
    
    time.sleep(5)
else:
    print("TIMEOUT: workflow still active after 300s")

# Check jobs
r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=hdrs(token))
jd = r.json()
jobs = jd.get("jobs", [])
print(f"\nTotal daemon jobs: {len(jobs)}")
for j in jobs:
    jid = j.get("job_id", j.get("id", ""))
    cmd = j.get("command", j.get("cmd", ""))
    st = j.get("status", "")
    print(f"  {jid[:12] if jid else '??'} | {st} | {cmd[:80]}")

# Check for duplicates
commands = [j.get("command", j.get("cmd","")) for j in jobs]
from collections import Counter
dupes = {c: n for c, n in Counter(commands).items() if n > 1}
if dupes:
    print(f"\n[WARN] Duplicate commands:")
    for c, n in dupes.items():
        print(f"  x{n}: {c[:80]}")
else:
    print("\n[PASS] No duplicate commands")

# Token stats
r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=hdrs(token))
ts = r.json()
print(f"\nToken stats: {ts.get('total_tokens',0)} total, {ts.get('total_turns',0)} turns")
print(f"  Prompt: {ts.get('total_prompt_tokens',0)}, Completion: {ts.get('total_completion_tokens',0)}")
ratio = ts.get('total_prompt_tokens',0) / max(ts.get('total_completion_tokens',1), 1)
print(f"  Ratio: {ratio:.1f}:1")