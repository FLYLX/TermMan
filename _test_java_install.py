import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Install Java 17 - should create a multi-step workflow
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u5e2e\u6211\u5b89\u88c5 openjdk-17-jdk-headless\uff0c\u88c5\u5b8c\u8dd1 java -version \u9a8c\u8bc1", "history": []},
    headers=h)
print(f"Install: {r2.status_code} {r2.json().get('content', '')[:150]}")

# Wait for workflow to progress through multiple steps
print("Waiting 40s for multi-step workflow...")
time.sleep(40)

# Check workflow
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r3.json()
for wf in wf_data.get("workflows", []):
    print(f"\nWF {wf['workflow_id'][:8]}: status={wf.get('status')}")
    print(f"  objective: {wf.get('objective')[:100]}")
    print(f"  report_sent_at: {wf.get('report_sent_at')}")
    steps = wf.get("steps", [])
    for i, s in enumerate(steps):
        ev = (s.get('evidence') or '')[:80]
        print(f"  step {i+1}: [{s.get('status')}] {s.get('title')} | ev={ev}")
    jobs = wf.get("jobs", [])
    print(f"  jobs: {len(jobs)}")
    for j in jobs[-5:]:
        print(f"    [{j.get('status')}] {j.get('command','')[:80]}")
