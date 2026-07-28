# -*- coding: utf-8 -*-
"""Complex test via simulated QQ path only: install java21 + concurrent QQ chatter."""
import requests, time, json, threading, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"  # 测试项目-5
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

def qq_dispatch(msg, sender_id="2537134688", timeout=120):
    """Simulated QQ private message via bridge dispatch API."""
    payload = {
        "sender_key": f"private_{sender_id}",
        "text": msg,
        "reply_target": {
            "target_type": "private",
            "target_id": sender_id,
            "metadata": {"sender_name": "FLY", "sender_id": sender_id, "conversation_type": "private"}
        }
    }
    try:
        r = requests.post(f"{BASE}/api/v1/robots/items/{ITEM_ID}/dispatch",
                          json=payload,
                          headers={"X-Termman-Bridge-Token": BRIDGE_TOKEN},
                          timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:
        return 0, str(e)

def get_workflows(h):
    return requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=h, timeout=10).json()

def get_jobs(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=h, timeout=10).json()

def get_tokens(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=h, timeout=10).json()

# ============ MAIN ============
print("=" * 60)
print("QQ-PATH COMPLEX TEST: Java 21 install + QQ chatter")
print("=" * 60)

token = login()
h = {"Authorization": f"Bearer {token}"}

# Clear session for a clean run
requests.delete(f"{BASE}/api/v1/memory/{ITEM_ID}/session", headers=h, timeout=10)
time.sleep(1)

baseline = get_tokens(h)
print(f"[BASELINE] tokens={baseline.get('total_tokens',0)} turns={baseline.get('total_turns',0)}")

# ---- PHASE 1: main task via QQ ----
print("\n[PHASE 1] QQ dispatch: install java21")
t0 = time.time()
s, r = qq_dispatch("帮我安装 openjdk-21-jdk-headless，装完跑 java -version 验证一下", timeout=60)
print(f"  dispatch -> status={s}: {json.dumps(r, ensure_ascii=False)[:200]}")

# ---- PHASE 2: concurrent QQ chatter while install runs ----
chatter = []
def send_chatter(msg, delay):
    time.sleep(delay)
    st, resp = qq_dispatch(msg, timeout=60)
    reason = resp.get("reason", "") if isinstance(resp, dict) else str(resp)
    chatter.append((msg, st, reason))
    print(f"  [QQ +{delay}s] '{msg}' -> {st} reason={reason}")

threads = [
    threading.Thread(target=send_chatter, args=("小柴在干嘛呀", 10)),
    threading.Thread(target=send_chatter, args=("今天星期几", 25)),
    threading.Thread(target=send_chatter, args=("安装进度怎么样了", 45)),
]
for t in threads:
    t.start()

# ---- Monitor workflow ----
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
    if not active and elapsed > 15:
        print(f"\n[MONITOR] all workflows settled after {elapsed}s")
        done = True
        break

for t in threads:
    t.join(timeout=30)

if not done:
    print("[MONITOR] TIMEOUT after 10min")

# ---- PHASE 3: results ----
print("\n" + "=" * 60)
print("[PHASE 3] Results")
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
print(f"\n  Jobs total: {len(jobs)}")
from collections import Counter
dupes = {c: n for c, n in Counter(j.get("command","") for j in jobs).items() if n > 1}
print(f"  Duplicates: {dupes if dupes else 'none'}")

print(f"\n  Chatter results:")
for msg, st, reason in chatter:
    print(f"    '{msg}' -> {st} {reason}")

final = get_tokens(h)
print(f"\n  Tokens: +{final.get('total_tokens',0)-baseline.get('total_tokens',0)} "
      f"(prompt +{final.get('total_prompt_tokens',0)-baseline.get('total_prompt_tokens',0)}, "
      f"completion +{final.get('total_completion_tokens',0)-baseline.get('total_completion_tokens',0)}), "
      f"turns +{final.get('total_turns',0)-baseline.get('total_turns',0)}")
print("\n[SCRIPT DONE]")
