# -*- coding: utf-8 -*-
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

print(f"=== CHECK at {time.strftime('%H:%M:%S')} ===")

# Tokens
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")

# Jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','running')}] {j.get('job_id','')} cmd={str(j.get('command',''))[:70]}")

# Workflow
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"Workflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"  [{w.get('status')}] {w.get('note', '')[:80]}")
        for s in w.get("steps", []):
            print(f"    [{s.get('status')}] {s.get('title')}")

# Last messages
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=10&offset=0", headers=h, timeout=10)
msgs = r2.json().get("messages", [])
print(f"\nSession ({len(msgs)} msgs):")
for m in msgs:
    mtype = m.get("type", "")
    tool = m.get("tool_name", "")
    content = str(m.get("content", ""))[:160]
    print(f"  [{mtype}|{tool}] {content}")