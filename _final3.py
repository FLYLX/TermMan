# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"=== FINAL STATUS ===")
print(f"Total: {td['total_tokens']} tokens, {td['total_turns']} turns")
print(f"Prompt: {td['total_prompt_tokens']}, Completion: {td['total_completion_tokens']}")
print(f"vs 100K baseline: {td['total_tokens']*100//100000}%")

r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','?')}] {j.get('job_id','')} elapsed={j.get('elapsed_seconds',0):.0f}s")

# Last messages
r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h, timeout=10)
msgs = r2.json().get("messages", [])
for m in msgs[-3:]:
    print(f"  [{m.get('type','')}] {str(m.get('content',''))[:200]}")