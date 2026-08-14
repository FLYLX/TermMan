# -*- coding: utf-8 -*-
"""NapCat-simulated complex test for 测试项目-5.
Pushes OneBot v11 private message events via the bridge HTTP event endpoint
(POST /onebot/v11/) — same path a real NapCat client uses — while the existing
mock_napcat.py process captures bot replies into _mock_qq.log.
Task: install java21 + concurrent QQ chatter."""
import requests, time, json, threading, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"  # 测试项目-5
SENDER_QQ = 2537134688
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"

_msg_id = int(time.time()) % 100000 * 10

def send_qq_event(text):
    """Push a private message event exactly like NapCat would."""
    global _msg_id
    _msg_id += 1
    evt = {
        "time": int(time.time()),
        "self_id": 10001,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": _msg_id,
        "user_id": SENDER_QQ,
        "message": [{"type": "text", "data": {"text": text}}],
        "raw_message": text,
        "font": 0,
        "sender": {"user_id": SENDER_QQ, "nickname": "FLY"},
    }
    r = requests.post(f"{BRIDGE}/onebot/v11/", json=evt,
                      headers={"X-Self-ID": "10001"}, timeout=15)
    print(f"  [QQ>>>] '{text[:50]}' -> HTTP {r.status_code}")
    return r.status_code

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

def get_workflows(h):
    return requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=h, timeout=10).json()

def get_jobs(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=h, timeout=10).json()

def get_tokens(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=h, timeout=10).json()

print("=" * 60)
print("NAPCAT-SIM TEST: java21 install via OneBot v11 HTTP event")
print("=" * 60)

with open(LOG, encoding="utf-8", errors="replace") as f:
    log_offset = len(f.readlines())  # only look at replies after this point

token = login()
h = {"Authorization": f"Bearer {token}"}
requests.delete(f"{BASE}/api/v1/memory/{ITEM_ID}/session", headers=h, timeout=10)
time.sleep(1)
baseline = get_tokens(h)
print(f"[BASELINE] tokens={baseline.get('total_tokens',0)} turns={baseline.get('total_turns',0)}")

# ---- main task + chatter, all as QQ events ----
t0 = time.time()
print("\n[PHASE 1] push install task as QQ event")
send_qq_event("帮我安装 openjdk-21-jdk-headless，装完跑 java -version 验证一下")

def chatter(text, delay):
    time.sleep(delay)
    send_qq_event(text)

threads = [
    threading.Thread(target=chatter, args=("小柴在干嘛呀", 15)),
    threading.Thread(target=chatter, args=("安装进度怎么样了", 40)),
]
for t in threads:
    t.start()

# ---- monitor ----
print("\n[MONITOR] polling workflows...")
done = False
for i in range(120):  # up to 10 min
    time.sleep(5)
    elapsed = int(time.time() - t0)
    wf = get_workflows(h)
    workflows = wf.get("workflows", [])
    active = [w for w in workflows if w.get("status") in ("running", "pending")]
    if i % 3 == 0 or not active:
        for w in workflows:
            steps = w.get("steps", [])
            sd = sum(1 for x in steps if x.get("status") in ("completed", "cancelled", "failed"))
            print(f"  [{elapsed}s] WF {w.get('status')} | {w.get('title','')[:40]} | {sd}/{len(steps)} steps")
    if not active and elapsed > 20:
        print(f"[MONITOR] all workflows settled after {elapsed}s")
        done = True
        break

for t in threads:
    t.join(timeout=30)
time.sleep(8)  # let final replies land in the log
if not done:
    print("[MONITOR] TIMEOUT after 10min")

# ---- results ----
print("\n" + "=" * 60)
print("[RESULTS]")
print("=" * 60)
wf = get_workflows(h)
for w in wf.get("workflows", []):
    print(f"  WF {str(w.get('id'))[:8]} status={w.get('status')} title={w.get('title','')[:50]}")
    for st in w.get("steps", []):
        print(f"    step {st.get('order')}: {st.get('title','')[:40]} [{st.get('status')}] attempts={st.get('attempts',0)}")
    for j in w.get("jobs", []):
        print(f"    job: {j.get('command','')[:70]} [{j.get('status')}] exit={j.get('exit_code')} success={j.get('success')}")

jd = get_jobs(h)
jobs = jd.get("jobs", [])
from collections import Counter
dupes = {c: n for c, n in Counter(j.get("command", "") for j in jobs).items() if n > 1}
print(f"\n  Jobs total: {len(jobs)}, duplicates: {dupes if dupes else 'none'}")

with open(LOG, encoding="utf-8", errors="replace") as f:
    new_lines = f.readlines()[log_offset:]
print(f"\n  QQ replies captured by mock_napcat during test: {len(new_lines)}")
for line in new_lines:
    print(f"    {line.rstrip()[:180]}")

final = get_tokens(h)
print(f"\n  Tokens: +{final.get('total_tokens',0)-baseline.get('total_tokens',0)}, "
      f"turns +{final.get('total_turns',0)-baseline.get('total_turns',0)}")

res = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "java", "-version"],
                     capture_output=True, text=True, timeout=15)
ver = (res.stderr or res.stdout).strip().splitlines()
print(f"\n  docker exec java -version: exit={res.returncode}")
for line in ver[:3]:
    print(f"    {line}")
print("  [PASS] java installed" if res.returncode == 0 else "  [FAIL] java not installed")
print("\n[SCRIPT DONE]")
