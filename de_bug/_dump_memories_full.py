# -*- coding: utf-8 -*-
import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories?limit=100", headers=h, timeout=15)
data = r.json()
mems = data.get("memories") or data.get("items") or data
if isinstance(mems, dict):
    mems = mems.get("memories", [])
for m in mems:
    print(json.dumps(m, ensure_ascii=False)[:600])
    print("---")
