import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

last_total = 0
stuck_count = 0
for check in range(12):
    time.sleep(15)
    
    # Session
    r3 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
    total = r3.json().get("total", 0)
    if last_total == 0:
        last_total = total
    delta = total - last_total
    last_total = total
    
    if delta == 0:
        stuck_count += 1
    else:
        stuck_count = 0
    
    # Workflow
    r2 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
    wf = r2.json()
    wf_info = "no_wf"
    for w in wf.get("workflows", []):
        steps = " | ".join([f"{s.get('title','')[:20]}:{s.get('status','')[:4]}" for s in w.get("steps", [])])
        wf_info = f"{w.get('status')} [{steps}]"
    
    # Jobs
    r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
    jobs = r4.json()
    active_jobs = len([j for j in jobs.get("jobs", []) if j.get("status") == "running"])
    
    # MC process
    jr = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
        "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
        capture_output=True, text=True)
    mc = jr.stdout.strip()
    
    # Daemon mem
    mr = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
        "cat /proc/1/status | grep VmRSS | awk '{print $2}'"],
        capture_output=True, text=True)
    mem = mr.stdout.strip()
    
    status = "OK" if stuck_count == 0 else f"STUCK x{stuck_count}"
    print(f"[{(check+1)*15:>3}s] +{delta} sess={total} jobs={active_jobs} mc={mc} mem={mem}kB {status} | {wf_info}")
    
    if stuck_count >= 4:
        print("\n!!! STUCK 60s+ - dumping last messages !!!")
        r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h)
        d5 = r5.json()
        msgs = d5 if isinstance(d5, list) else d5.get("messages", d5.get("history", []))
        for m in msgs:
            print(f"  {m.get('role')}: {str(m.get('content',''))[:200]}")
        
        # Check backend logs for errors
        lr = subprocess.run(["docker", "logs", "TermPaws-backend-1", "--tail", "20"],
            capture_output=True, text=True)
        errs = [l for l in lr.stderr.split('\n') if 'ERROR' in l or 'error' in l.lower()]
        if errs:
            print("\nBackend errors:")
            for e in errs[-5:]:
                print(f"  {e[:200]}")
        break
    
    if wf.get("count", 0) == 0 and total > 3076:
        print(">>> Workflow done <<<")
        # Show final reply
        r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=2&offset=0", headers=h)
        d5 = r5.json()
        msgs = d5 if isinstance(d5, list) else d5.get("messages", d5.get("history", []))
        for m in msgs[:2]:
            print(f"  {m.get('role')}: {str(m.get('content',''))[:250]}")
        break