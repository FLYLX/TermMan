# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Get full session to find hello_3
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=20&offset=0", headers=h, timeout=10)
msgs = r2.json().get("messages", [])
print(f"Total msgs: {len(msgs)}")
for m in msgs:
    mtype = m.get("type", "")
    content = str(m.get("content", ""))
    # Show messages related to hello or echo
    if "hello" in content.lower() or "echo" in content.lower() or mtype in ("chat_user", "agent_response"):
        print(f"  [{mtype}] {content[:200]}")
        print("  ---")