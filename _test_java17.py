import requests, json, time

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Install Java 17 - multi-step task
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u5e2e\u6211\u5b89\u88c5 Java 17\uff0c\u88c5\u5b8c\u9a8c\u8bc1 java -version", "history": []},
    headers=h)
print("Response:", r2.status_code)
resp = r2.json()
print("Content:", resp.get("content", "")[:300])

# Wait for workflow to be created and jobs to run
print("\nWaiting 20s for workflow progress...")
time.sleep(20)

# Check workflow
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r3.json()
for wf in wf_data.get("workflows", []):
    print(f"\nWF {wf['workflow_id'][:8]}: status={wf.get('status')}")
    print(f"  objective: {wf.get('objective')}")
    steps = wf.get("steps", [])
    for i, s in enumerate(steps):
        ev = (s.get('evidence') or '')[:80]
        print(f"  step {i+1}: [{s.get('status')}] {s.get('title')} | ev={ev}")
    jobs = wf.get("jobs", [])
    print(f"  jobs: {len(jobs)}")
    for j in jobs[-5:]:
        print(f"    [{j.get('status')}] {j.get('command','')[:80]}")
