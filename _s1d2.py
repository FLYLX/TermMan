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
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"[{w.get('status')}]")
        for s in w.get("steps", []):
            print(f"  [{s.get('status')}] {s.get('title')} att={s.get('attempts',0)}")

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"Tokens: total={td['total_tokens']}, turns={td['total_turns']}")
print(f"Jobs: {requests.get(f'{BASE}/api/v1/items/{ITEM}/jobs', headers=h, timeout=10).json().get('count',0)}")

# Last messages
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h, timeout=10)
for m in r2.json().get("messages", []):
    mtype = m.get("type","")
    if mtype in ("agent_response", "agent_thinking"):
        print(f"\n[{mtype}] {str(m.get('content',''))[:250]}")