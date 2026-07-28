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
print(f"Total: {d['total_tokens']} tokens, {d['total_turns']} turns")
print(f"Prompt: {d['total_prompt_tokens']}, Completion: {d['total_completion_tokens']}")
if d['total_turns'] > 0:
    print(f"Ratio: {d['total_prompt_tokens']/max(d['total_completion_tokens'],1):.1f}:1")
    print(f"Avg prompt/turn: {d['total_prompt_tokens']/d['total_turns']:.0f}")

r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"\nWorkflows: {wf.get('count', 0)}")
if wf.get("workflows"):
    for w in wf["workflows"]:
        print(f"  [{w.get('status')}] {w.get('note', '')[:80]}")
        for s in w.get("steps", []):
            print(f"    [{s.get('status')}] {s.get('title')}")

r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"\nJobs: {jobs.get('count', 0)}")
for j in jobs.get("jobs", []):
    print(f"  [{j.get('status')}] {str(j.get('command',''))[:80]}")

# Check java
import subprocess
result = subprocess.run(["docker", "exec", "termman-daemon-1", "java", "-version"], capture_output=True, text=True)
print(f"\nJava: {result.stderr[:200] if result.stderr else result.stdout[:200]}")