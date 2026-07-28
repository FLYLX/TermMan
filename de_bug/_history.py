# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=15&offset=0", headers=h, timeout=10)
data = r2.json()
msgs = data.get("messages", data) if isinstance(data, dict) else data
for m in (msgs if isinstance(msgs, list) else []):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:200]
    mtype = m.get("type", "")
    tool = m.get("tool_name", "")
    ts = m.get("timestamp", "")[-8:]
    print(f"[{ts}|{mtype}|{tool}] {content}")
    print("---")