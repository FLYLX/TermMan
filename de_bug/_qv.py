# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

subprocess.run(["docker", "exec", "TermPaws-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

# Remove sl first
subprocess.run(["docker", "exec", "TermPaws-daemon-1", "bash", "-c", "apt-get remove -y sl 2>/dev/null"], capture_output=True, timeout=15)

print("=== QUICK VERIFY: install sl ===")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "安装sl，装完跑一下验证",
    "history": []
}, headers=h, timeout=120)
print(f"Reply: {r2.json().get('content','')[:150]}")

# Wait for completion
for i in range(6):
    time.sleep(15)
    r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
    wf = r4.json()
    count = wf.get("count", 0)
    if count > 0:
        w = wf["workflows"][0]
        status = w.get("status")
        steps = [(s.get("status"), s.get("title"), s.get("attempts",0)) for s in w.get("steps",[])]
        print(f"  [{i*15}s] wf={status} steps={steps}")
        if status in ("completed", "ready_to_report"):
            break
    else:
        r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
        td = r3.json()
        print(f"  [{i*15}s] no wf, tokens={td['total_tokens']}, turns={td['total_turns']}")

# Final
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"\nFINAL: tokens={td['total_tokens']}, turns={td['total_turns']}")
print(f"Jobs: {requests.get(f'{BASE}/api/v1/items/{ITEM}/jobs', headers=h, timeout=10).json().get('count',0)}")

# Last response
r2s = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h, timeout=10)
for m in r2s.json().get("messages", []):
    if m.get("type") == "agent_response":
        print(f"Report: {str(m.get('content',''))[:200]}")