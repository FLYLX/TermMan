# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

# Remove jq and curl first so the test is meaningful
subprocess.run(["docker", "exec", "termman-daemon-1", "bash", "-c",
    "apt-get remove -y jq curl 2>/dev/null; which jq curl 2>&1 || echo REMOVED"],
    capture_output=True, timeout=30)

print("=== SCENARIO 1: install jq + curl ===")
t0 = time.time()
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "帮我安装 jq 和 curl，装完验证一下版本",
    "history": []
}, headers=h, timeout=120)
d = r2.json()
print(f"Reply: {d.get('content','')[:200]}")
print(f"Time: {time.time()-t0:.1f}s")