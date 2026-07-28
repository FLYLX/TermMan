# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=100&offset=0", headers=h, timeout=10)
data = r2.json()
msgs = data.get("messages", [])
print(f"Session messages: {len(msgs)}")
total_chars = sum(len(str(m.get("content", ""))) for m in msgs)
print(f"Total content chars: {total_chars}")

# Check how many are included in prompt (recent context)
from_types = {}
for m in msgs:
    t = m.get("type", "unknown")
    from_types[t] = from_types.get(t, 0) + 1
print(f"By type: {json.dumps(from_types)}")