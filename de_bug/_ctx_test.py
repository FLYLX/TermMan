# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "hi", "history": []}, headers=h, timeout=60)
print(f"Reply: {r2.json().get('content','')[:100]}")

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"Prompt: {td['total_prompt_tokens']}, Comp: {td['total_completion_tokens']}, Turns: {td['total_turns']}")
print(f"Before context fix: 5928 prompt. Now: {td['total_prompt_tokens']}. Saved: {5928 - td['total_prompt_tokens']}")