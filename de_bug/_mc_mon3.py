import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

for check in range(4):
    print(f"\n{'='*50}")
    print(f"Check {check+1}/4 (waiting 40s...)")
    time.sleep(40)

    # Workflows
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
    wf = r.json()
    for w in wf.get("workflows", []):
        print(f"Workflow: status={w.get('status')}")
        for s in w.get("steps", []):
            print(f"  [{s.get('status'):>10}] {s.get('title','')[:55]} att={s.get('attempts',0)}")

    # Jobs
    r = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
    jobs = r.json()
    active = [j for j in jobs.get("jobs", []) if j.get("status") == "running"]
    print(f"Active jobs: {len(active)}")
    for j in active:
        print(f"  {j.get('job_id','?')[:12]} cmd={str(j.get('command',''))[:100]}")

    # Session
    r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
    total = r.json().get("total", 0)
    print(f"Session: {total}")

    # Last 2 messages
    r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=2&offset=0", headers=h)
    data = r.json()
    msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
    for m in msgs[:2]:
        print(f"  {m.get('role')}: {str(m.get('content',''))[:180]}")