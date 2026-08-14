"""Concurrent Task Test: Python 3.6 (Cancel) + Java 21 (Complete)."""
import requests, time, json, subprocess

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
BASELINE_TOKENS = 19964300
BASELINE_TURNS = 1917

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    return r.json()["access_token"]

def hdrs(t):
    return {"Authorization": f"Bearer {t}"}

def send_chat(token, msg, timeout=180):
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM_ID}",
                          json={"message": msg, "history": []},
                          headers=hdrs(token), timeout=timeout)
        return r.status_code, r.json() if "json" in r.headers.get("content-type","") else r.text
    except Exception as e:
        return 0, str(e)

def get_workflows(token):
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs(token))
    return r.json().get("workflows", [])

def get_jobs(token):
    r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=hdrs(token))
    return r.json().get("jobs", [])

def get_tokens(token):
    r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=hdrs(token))
    return r.json()

def print_status(token, label):
    wfs = get_workflows(token)
    jobs = get_jobs(token)
    tokens = get_tokens(token)
    
    total_tok = tokens.get("total_tokens", 0)
    delta_tok = total_tok - BASELINE_TOKENS
    delta_turns = tokens.get("total_turns", 0) - BASELINE_TURNS
    
    print(f"\n[{label}] Tokens: +{delta_tok} | Turns: +{delta_turns}")
    print(f"  Workflows: {len(wfs)}")
    for w in wfs:
        steps = w.get("steps", [])
        done = sum(1 for s in steps if s.get("status") in ("completed","cancelled","failed"))
        print(f"    WF {w['workflow_id'][:8]} | {w['status']} | {w.get('objective','')[:40]} | {done}/{len(steps)} steps")
        for s in steps:
            print(f"      Step: {s.get('title','')[:30]} [{s.get('status')}]")
    
    running_jobs = [j for j in jobs if j.get("status") == "running"]
    print(f"  Jobs: {len(jobs)} total, {len(running_jobs)} running")
    for j in running_jobs:
        cmd = j.get("command", j.get("cmd", ""))
        print(f"    RUNNING: {cmd[:60]}")

# ============ MAIN ============
print("=" * 60)
print("CONCURRENT TEST: Python 3.6 (Cancel) + Java 21 (Complete)")
print("=" * 60)

token = login()

# Phase 1: Start Python 3.6
print("\n[PHASE 1] Sending Python 3.6 install...")
status, resp = send_chat(token, "帮我从源码编译安装 Python 3.6，装完验证版本")
print(f"  Status: {status}, Reply: {str(resp)[:100]}")

time.sleep(3)

# Phase 2: Start Java 21
print("\n[PHASE 2] Sending Java 21 install...")
status, resp = send_chat(token, "同时帮我安装 openjdk-21-jdk-headless，装完跑 java -version 验证")
print(f"  Status: {status}, Reply: {str(resp)[:100]}")

# Monitor for 20s to let jobs start
print("\n[MONITOR] Waiting 20s for jobs to start...")
for i in range(4):
    time.sleep(5)
    print_status(token, f"{(i+1)*5}s")

# Phase 3: Cancel Python
print("\n[PHASE 3] Cancelling Python 3.6...")
status, resp = send_chat(token, "Python 3.6 编译太慢了，取消安装 Python 的任务，只保留 Java 安装")
print(f"  Status: {status}, Reply: {str(resp)[:100]}")

# Phase 4: Monitor until completion
print("\n[MONITOR] Waiting for completion (max 5 mins)...")
start_time = time.time()
for i in range(60):
    time.sleep(5)
    elapsed = int(time.time() - start_time)
    print_status(token, f"{elapsed}s")
    
    wfs = get_workflows(token)
    active = [w for w in wfs if w.get("status") not in ("completed", "cancelled", "failed", "")]
    if not active and elapsed > 10:
        print(f"\n[DONE] All workflows terminal after {elapsed}s")
        break
else:
    print("\n[TIMEOUT] 5 minutes reached")

# Final Verification
print("\n" + "=" * 60)
print("FINAL VERIFICATION")
print("=" * 60)

# Check Java
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "java", "-version"],
                       capture_output=True, text=True, timeout=10)
print(f"Java: exit={result.returncode}")
if result.returncode == 0:
    print(f"  [PASS] {result.stderr.splitlines()[0] if result.stderr else 'Installed'}")
else:
    print(f"  [FAIL] Not installed")

# Check Python 3.6
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "python3.6", "--version"],
                       capture_output=True, text=True, timeout=10)
print(f"Python 3.6: exit={result.returncode}")
if result.returncode != 0:
    print(f"  [PASS] Not installed (cancelled successfully)")
else:
    print(f"  [WARN] Installed: {result.stdout.strip()}")

# Final Token Stats
tokens = get_tokens(token)
total_tok = tokens.get("total_tokens", 0)
delta_tok = total_tok - BASELINE_TOKENS
delta_turns = tokens.get("total_turns", 0) - BASELINE_TURNS
print(f"\nToken Usage: +{delta_tok} tokens, +{delta_turns} turns")
print(f"  Prompt: +{tokens.get('total_prompt_tokens',0) - 18884163}")
print(f"  Completion: +{tokens.get('total_completion_tokens',0) - 1080137}")