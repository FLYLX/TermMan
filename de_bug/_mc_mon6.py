import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

for check in range(6):
    print(f"\n--- Check {check+1}/6 (30s) ---")
    time.sleep(30)

    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
    wf = r.json()
    for w in wf.get("workflows", []):
        print(f"WF: status={w.get('status')}")
        for s in w.get("steps", []):
            print(f"  [{s.get('status'):>10}] {s.get('title','')[:55]} att={s.get('attempts',0)}")

    r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
    total = r.json().get("total", 0)
    print(f"Session: {total}")

    result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
        "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
        capture_output=True, text=True)
    mc = result.stdout.strip()
    print(f"MC process: {mc}")

    r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
    data = r.json()
    msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
    if msgs:
        print(f"Last: {msgs[0].get('role')}: {str(msgs[0].get('content',''))[:200]}")

    if mc == "1":
        print(">>> MC SERVER RUNNING! <<<")
        break
    if wf.get("count", 0) == 0:
        print(">>> Workflow completed/cleaned <<<")
        break