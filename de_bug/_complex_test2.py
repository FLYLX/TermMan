"""Complex task test: install Java + concurrent chatter + QQ messages."""
import requests, time, json, threading, sys

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT_ID = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    r.raise_for_status()
    return r.json()["access_token"]

def hdrs(token):
    return {"Authorization": f"Bearer {token}"}

def web_chat(token, msg, timeout=180):
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM_ID}",
                          json={"message": msg, "history": []},
                          headers=hdrs(token), timeout=timeout)
        return r.status_code, r.json() if "json" in r.headers.get("content-type","") else r.text
    except Exception as e:
        return 0, str(e)

def qq_dispatch(msg, sender_id="2537134688", sender_name="FLY", timeout=120):
    payload = {
        "sender_key": f"private_{sender_id}",
        "text": msg,
        "reply_target": {
            "target_type": "private",
            "target_id": sender_id,
            "metadata": {"sender_name": sender_name, "sender_id": sender_id, "conversation_type": "private"}
        }
    }
    try:
        r = requests.post(f"{BASE}/api/v1/robots/{ROBOT_ID}/dispatch",
                          json=payload,
                          headers={"X-Termman-Bridge-Token": BRIDGE_TOKEN},
                          timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:
        return 0, str(e)

def get_workflows(token):
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=hdrs(token))
    return r.json()

def get_jobs(token):
    r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=hdrs(token))
    return r.json()

def get_token_stats(token):
    r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=hdrs(token))
    return r.json()

def print_workflows(token, label=""):
    wf = get_workflows(token)
    workflows = wf.get("workflows", [])
    if not workflows:
        print(f"  [{label}] No active workflows")
        return
    for w in workflows:
        steps = w.get("steps", [])
        done = sum(1 for s in steps if s.get("status") in ("completed","cancelled","failed"))
        print(f"  [{label}] WF {w['id'][:8]} | {w['status']} | {w.get('title','')} | {done}/{len(steps)} steps")
        for s in steps:
            print(f"    Step {s.get('order')}: {s.get('title')} [{s.get('status')}] attempts={s.get('attempts',0)}")

def print_jobs(token, label=""):
    jd = get_jobs(token)
    jobs = jd.get("jobs", [])
    running = [j for j in jobs if j.get("status") == "running"]
    print(f"  [{label}] Jobs: {len(jobs)} total, {len(running)} running")
    for j in running:
        cmd = j.get("command", j.get("cmd", ""))
        print(f"    RUNNING: {cmd[:80]}")

# ============ MAIN ============
print("=" * 60)
print("COMPLEX TEST: Java Install + Concurrent Chatter")
print("=" * 60)

token = login()
baseline = get_token_stats(token)
print(f"[BASELINE] Tokens: {baseline.get('total_tokens',0)}, Turns: {baseline.get('total_turns',0)}")

# First, clean up any existing java
print("\n[CLEANUP] Removing existing java...")
status, resp = web_chat(token, "帮我卸载 openjdk-21-jre-headless，如果有的话。卸完确认 java -version 找不到", timeout=180)
print(f"  Cleanup status: {status}")
if isinstance(resp, dict):
    print(f"  Reply: {resp.get('content','')[:200]}")

# Wait for cleanup workflow
print("  Waiting for cleanup...")
for i in range(30):
    time.sleep(5)
    wf = get_workflows(token)
    active = [w for w in wf.get("workflows",[]) if w.get("status") in ("running","pending")]
    if not active:
        print(f"  Cleanup done after {(i+1)*5}s")
        break
    print_workflows(token, f"cleanup {(i+1)*5}s")

time.sleep(3)

# ---- PHASE 1: Start Java install ----
print("\n" + "=" * 60)
print("PHASE 1: Start Java 21 install via web chat")
print("=" * 60)
t0 = time.time()
status, resp = web_chat(token, "帮我安装 openjdk-21-jdk-headless，装完跑 java -version 验证", timeout=180)
elapsed = time.time() - t0
print(f"  Status: {status}, Time: {elapsed:.1f}s")
if isinstance(resp, dict):
    print(f"  Reply: {resp.get('content','')[:300]}")

# ---- PHASE 2: Send chatter while task runs ----
print("\n" + "=" * 60)
print("PHASE 2: Concurrent chatter (QQ + web)")
print("=" * 60)

chatter_results = []

def send_qq_chatter(msg, delay):
    time.sleep(delay)
    s, r = qq_dispatch(msg)
    chatter_results.append(("QQ", msg, s, r))
    print(f"  [QQ +{delay}s] '{msg}' -> status={s}")

def send_web_chatter(msg, delay):
    time.sleep(delay)
    s, r = web_chat(token, msg, timeout=120)
    chatter_results.append(("WEB", msg, s, r))
    content = r.get("content","")[:100] if isinstance(r, dict) else str(r)[:100]
    print(f"  [WEB +{delay}s] '{msg}' -> status={s}, reply={content}")

# Start chatter threads
threads = [
    threading.Thread(target=send_qq_chatter, args=("小柴在干嘛呀", 5)),
    threading.Thread(target=send_web_chatter, args=("今天星期几", 10)),
    threading.Thread(target=send_qq_chatter, args=("给我讲个笑话", 20)),
]
for t in threads:
    t.start()

# Monitor workflow while chatter runs
print("\n  Monitoring workflow progress...")
for i in range(40):
    time.sleep(5)
    elapsed = int(time.time() - t0)
    print_workflows(token, f"{elapsed}s")
    print_jobs(token, f"{elapsed}s")
    
    # Check if workflow completed
    wf = get_workflows(token)
    active = [w for w in wf.get("workflows",[]) if w.get("status") in ("running","pending")]
    if not active and elapsed > 15:
        print(f"\n  Workflow completed after {elapsed}s")
        break

# Wait for chatter threads
for t in threads:
    t.join(timeout=30)

# ---- PHASE 3: Results ----
print("\n" + "=" * 60)
print("PHASE 3: Results")
print("=" * 60)

# Check java installed
print("\n  Checking java installation...")
status, resp = web_chat(token, "跑一下 java -version 看看装好没", timeout=120)
if isinstance(resp, dict):
    print(f"  Reply: {resp.get('content','')[:300]}")

time.sleep(10)

# Check workflows
print("\n  Final workflow state:")
print_workflows(token, "final")

# Check jobs for duplicates
jd = get_jobs(token)
jobs = jd.get("jobs", [])
print(f"\n  Total jobs: {len(jobs)}")
commands = [j.get("command", j.get("cmd","")) for j in jobs]
from collections import Counter
dupes = {cmd: cnt for cmd, cnt in Counter(commands).items() if cnt > 1}
if dupes:
    print(f"  [WARN] Duplicate commands found:")
    for cmd, cnt in dupes.items():
        print(f"    x{cnt}: {cmd[:80]}")
else:
    print("  [PASS] No duplicate commands")

# Check chatter results
print(f"\n  Chatter results: {len(chatter_results)}")
for source, msg, status, resp in chatter_results:
    if isinstance(resp, dict):
        content = resp.get("content", resp.get("reason", ""))[:100]
    else:
        content = str(resp)[:100]
    print(f"    [{source}] '{msg}' -> {status}: {content}")

# Token usage
final = get_token_stats(token)
total = final.get("total_tokens",0) - baseline.get("total_tokens",0)
turns = final.get("total_turns",0) - baseline.get("total_turns",0)
prompt = final.get("total_prompt_tokens",0) - baseline.get("total_prompt_tokens",0)
comp = final.get("total_completion_tokens",0) - baseline.get("total_completion_tokens",0)
print(f"\n  Token usage: {total} total ({prompt} prompt + {comp} completion)")
print(f"  Ratio: {prompt/max(comp,1):.1f}:1")
print(f"  Turns: {turns}")

print("\n[DONE] Complex test completed")