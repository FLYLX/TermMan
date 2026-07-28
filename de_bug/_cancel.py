# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Cancel the stale job via MCP
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "取消所有正在运行的后台任务",
    "history": []
}, headers=h, timeout=60)
print(f"Cancel request: {r2.status_code}")
print(f"Reply: {r2.json().get('content','')[:200]}")