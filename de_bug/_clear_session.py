# -*- coding: utf-8 -*-
import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=30)
print("clear session:", r.status_code, r.text[:100])
