# -*- coding: utf-8 -*-
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear token table
import subprocess
subprocess.run(["docker", "exec", "TermPaws-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

print("=== TEST 1: Web chat simple ===")
t0 = time.time()
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "你好呀", "history": []}, headers=h, timeout=60)
elapsed = time.time() - t0
print(f"  Status: {r2.status_code}, Time: {elapsed:.1f}s")
try:
    d = r2.json()
    print(f"  Reply: {d.get('content','')[:100]}")
except:
    print(f"  Raw: {r2.text[:100]}")

# Check tokens
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"  Tokens: prompt={td['total_prompt_tokens']}, completion={td['total_completion_tokens']}, turns={td['total_turns']}")