# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check java
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "bash", "-c", "java -version 2>&1 || echo NO_JAVA"], capture_output=True, text=True)
java_out = (result.stdout + result.stderr).strip()
print(f"Java: {java_out[:200]}")

# Check jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','running')}] {str(j.get('command',''))[:60]} elapsed={j.get('elapsed_seconds',0):.0f}s")

# Tokens
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"Tokens: prompt={td['total_prompt_tokens']}, comp={td['total_completion_tokens']}, turns={td['total_turns']}")
if td['total_completion_tokens'] > 0:
    print(f"Ratio: {td['total_prompt_tokens']/td['total_completion_tokens']:.1f}:1")