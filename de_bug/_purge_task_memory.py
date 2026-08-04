# -*- coding: utf-8 -*-
import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
MEM = "224d4990-ccba-4532-96cf-409dfcd137b1"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
for status in ("archived", "deleted", "inactive", "expired"):
    r = requests.post(f"{BASE}/api/v1/memory/{ITEM}/memories/{MEM}/status", json={"status": status}, headers=h, timeout=15)
    print(f"status={status} -> {r.status_code} {r.text[:120]}")
    if r.status_code == 200:
        break
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories?limit=100", headers=h, timeout=15)
mems = r.json()
mems = mems.get("memories") or mems.get("items") or mems
print("remaining:", [str(m.get("content"))[:40] for m in mems])
