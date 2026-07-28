# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"FINAL Tokens: prompt={td['total_prompt_tokens']}, comp={td['total_completion_tokens']}, turns={td['total_turns']}")
if td['total_completion_tokens'] > 0:
    print(f"Ratio: {td['total_prompt_tokens']/td['total_completion_tokens']:.1f}:1")
    print(f"Avg prompt/turn: {td['total_prompt_tokens']/max(td['total_turns'],1):.0f}")

# Check workflow
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"\nWorkflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"  [{w.get('status')}] {w.get('note', '')[:80]}")
        for s in w.get("steps", []):
            print(f"    [{s.get('status')}] {s.get('title')}")

# Check jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {str(j.get('command',''))[:80]}")

# Check last session messages
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h, timeout=10)
msgs = r2.json().get("messages", [])
print("\nLast messages:")
for m in msgs[-3:]:
    mtype = m.get("type", "")
    content = str(m.get("content", ""))[:150]
    print(f"  [{mtype}] {content}")