# -*- coding: utf-8 -*-
import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
MEM = "224d4990-ccba-4532-96cf-409dfcd137b1"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = requests.post(f"{BASE}/api/v1/memory/{ITEM}/memories/{MEM}/status", json={"status": "resolved"}, headers=h, timeout=15)
print(f"mark resolved -> {r.status_code} {r.text[:200]}")
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories?limit=200", headers=h, timeout=20)
data = r.json()
mems = data.get("memories") or data.get("items") or data
if isinstance(mems, dict):
    mems = mems.get("memories", [])
hit = [m for m in mems if str(m.get("id")) == MEM]
print("memory entry:", json.dumps({k: hit[0].get(k) for k in ("id","status","content")}, ensure_ascii=False)[:300] if hit else "NOT FOUND")
active_hits = [m for m in mems if str(m.get("id")) == MEM and str(m.get("status","active")).lower() == "active"]
print("still active?", bool(active_hits))
import json
