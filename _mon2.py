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
print(f"Tokens: prompt={td['total_prompt_tokens']}, comp={td['total_completion_tokens']}, total={td['total_tokens']}, turns={td['total_turns']}")

r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Jobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status','running')}] {j.get('job_id','')} elapsed={j.get('elapsed_seconds',0):.0f}s {str(j.get('command',''))[:60]}")

# Check java
result = subprocess.run(["docker", "exec", "termman-daemon-1", "bash", "-c", "java -version 2>&1 || echo NO_JAVA"], capture_output=True, text=True)
print(f"Java: {(result.stdout + result.stderr).strip()[:150]}")