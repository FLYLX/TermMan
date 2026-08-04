# -*- coding: utf-8 -*-
import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=100&offset=0", headers=h, timeout=15)
msgs = r.json().get("messages", [])
print("order check: [0] =", str(msgs[0].get("content"))[:40], " | [-1] =", str(msgs[-1].get("content"))[:40])
print("\n=== ls callback (index 5) ===")
print(msgs[5].get("content"))
print("\n=== thinking before it (index 4) ===")
print(msgs[4].get("content"))
print("\n=== thinking after it (index 6) ===")
print(msgs[6].get("content"))
