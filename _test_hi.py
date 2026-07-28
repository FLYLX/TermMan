# -*- coding: utf-8 -*-
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "hi", "history": []}, headers=h, timeout=60)
print(f"Chat: {r2.status_code}")

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
d = r3.json()
print(f"Prompt: {d['total_prompt_tokens']}, Completion: {d['total_completion_tokens']}, Turns: {d['total_turns']}")
print(f"Before: 4931 prompt. Now: {d['total_prompt_tokens']}. Saved: {4931 - d['total_prompt_tokens']} tokens")