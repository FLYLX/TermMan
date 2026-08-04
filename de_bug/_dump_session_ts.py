# -*- coding: utf-8 -*-
import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
sess = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=100", headers=h, timeout=10).json()
msgs = sess.get("messages") or sess.get("history") or []
print(f"total msgs: {len(msgs)}")
for i, m in enumerate(msgs):
    role = m.get("role")
    ts = m.get("timestamp") or m.get("created_at") or ""
    content = m.get("content")
    if isinstance(content, list):
        content = " ".join(str(c.get("text","")) for c in content if isinstance(c, dict))
    print(f"{i:03} [{ts}] [{role}] {str(content)[:150]}")
