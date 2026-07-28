# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"Workflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"  [{w.get('status')}] note={w.get('note', '')[:80]}")
        for s in w.get("steps", []):
            print(f"    [{s.get('status')}] {s.get('title')} att={s.get('attempts',0)}")

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")

r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
print(f"Jobs: {r5.json().get('count', 0)}")

# Last response
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h, timeout=10)
msgs = r2.json().get("messages", [])
for m in msgs:
    if m.get("type") == "agent_response":
        print(f"\nReport: {str(m.get('content',''))[:300]}")