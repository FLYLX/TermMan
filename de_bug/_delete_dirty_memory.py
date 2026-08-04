# -*- coding: utf-8 -*-
import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
MEM = "224d4990-ccba-4532-96cf-409dfcd137b1"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories/{MEM}", headers=h, timeout=15)
print("before:", r.status_code, str(r.json())[:200])
r = requests.delete(f"{BASE}/api/v1/memory/{ITEM}/memories/{MEM}", headers=h, timeout=15)
print("delete:", r.status_code, r.text[:150])
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories/{MEM}", headers=h, timeout=15)
print("after:", r.status_code, str(r.json())[:150])
