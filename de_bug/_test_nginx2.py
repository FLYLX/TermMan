import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Resolve blocked workflow
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "OpenJDK 21\u4e0d\u7528\u7ba1\uff0c\u53ea\u8981Corretto\u5220\u5e72\u51c0\u5c31\u884c\uff0c\u4efb\u52a1\u5b8c\u6210", "history": []},
    headers=h)
print(f"Resolve: {r2.status_code} {r2.json().get('content', '')[:150]}")

time.sleep(5)

# Fresh install nginx - multi-step
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u5e2e\u6211\u5b89\u88c5 nginx\uff0c\u88c5\u5b8c\u542f\u52a8\u5b83\uff0c\u7136\u540e\u9a8c\u8bc1 curl localhost \u80fd\u8fd4\u56de\u5185\u5bb9", "history": []},
    headers=h)
print(f"Nginx: {r3.status_code} {r3.json().get('content', '')[:150]}")

# Wait for workflow progress
print("Waiting 30s...")
time.sleep(30)

# Check workflow
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf_data = r4.json()
for wf in wf_data.get("workflows", []):
    print(f"\nWF {wf['workflow_id'][:8]}: status={wf.get('status')}")
    print(f"  objective: {wf.get('objective')[:80]}")
    steps = wf.get("steps", [])
    for i, s in enumerate(steps):
        ev = (s.get('evidence') or '')[:80]
        print(f"  step {i+1}: [{s.get('status')}] {s.get('title')} | ev={ev}")
    jobs = wf.get("jobs", [])
    print(f"  jobs: {len(jobs)}")
