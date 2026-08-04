# -*- coding: utf-8 -*-
import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}

print("=== last 6 tickets ===")
tasks = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage/by-task", headers=h, timeout=10).json()["tasks"]
for t in tasks[:6]:
    print(json.dumps({k: t.get(k) for k in ("request_message","ticket_status","turns","last_seen","source_type")}, ensure_ascii=False))

print("\n=== session tail (last 14) ===")
sess = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=100", headers=h, timeout=10).json()
msgs = sess.get("messages") or sess.get("history") or []
for m in msgs[-14:]:
    role = m.get("role")
    content = m.get("content")
    if isinstance(content, list):
        content = " ".join(str(c.get("text","")) for c in content if isinstance(c, dict))
    print(f"[{role}] {str(content)[:200]}")
