# -*- coding: utf-8 -*-
import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
subprocess.run(["docker", "exec", "TermPaws-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)
print("Token table cleared")

# Run baseline test
print("\n=== BASELINE RUN 1: 安装java21 ===")
t0 = time.time()
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "安装java21，装完验证版本",
    "history": []
}, headers=h, timeout=120)
elapsed = time.time() - t0
d = r2.json()
print(f"  HTTP: {r2.status_code}, Time: {elapsed:.1f}s")
print(f"  Reply: {d.get('content','')[:200]}")
print(f"  Start time: {time.strftime('%H:%M:%S')}")