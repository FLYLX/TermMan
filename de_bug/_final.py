# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
d = r3.json()
print(f"FINAL: {d['total_tokens']} tokens, {d['total_turns']} turns")
print(f"Prompt: {d['total_prompt_tokens']}, Completion: {d['total_completion_tokens']}")
if d['total_completion_tokens'] > 0:
    print(f"Ratio: {d['total_prompt_tokens']/d['total_completion_tokens']:.1f}:1")