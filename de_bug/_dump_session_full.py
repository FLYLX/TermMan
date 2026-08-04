# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=20&offset=0", headers=h, timeout=15)
msgs = r.json().get("messages", [])
print(f"total {len(msgs)} messages (newest first)")
for i, m in enumerate(msgs):
    print(f"--- [{i}] role={m.get('role')} type={m.get('type')}")
    print("   ", json.dumps({k:v for k,v in m.items() if k not in ('content',)}, ensure_ascii=False)[:300])
    print("    content:", str(m.get('content',''))[:300].replace(chr(10),' '))
