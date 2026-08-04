# -*- coding: utf-8 -*-
"""Complex scenario: 2 concurrent QQ tasks + mid-flight chatter + follow-up task.
Monitors plan table (item plan + per-task cards) lifecycle throughout."""
import requests, json, sys, io, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
SENDER = "2537134688"

token = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
t0 = time.time()
def stamp(): return f"[{time.time()-t0:6.1f}s]"

def qq(msg, timeout=60):
    payload = {"sender_key": f"private_{SENDER}", "text": msg,
               "reply_target": {"target_type": "private", "target_id": SENDER,
                                "metadata": {"sender_name": "FLY", "sender_id": SENDER, "conversation_type": "private"}}}
    try:
        r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
                          headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=timeout)
        return r.status_code, (r.json().get("reason") if r.ok else r.text[:80])
    except Exception as e:
        return 0, str(e)[:80]

def get_plan():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=5).json().get("plan", [])
    except Exception:
        return []

def get_task_cards():
    """What the frontend PlanPanel renders as task cards (new filter logic included)."""
    try:
        tasks = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage/by-task", headers=h, timeout=8).json().get("tasks", [])
    except Exception:
        return []
    now = time.time() * 1000
    cards = []
    for t in tasks:
        plan = t.get("plan", [])
        if not plan:
            continue
        all_done = all(s.get("status") == "completed" for s in plan)
        last_seen = t.get("last_seen", "")
        if all_done and last_seen:
            try:
                ls = time.mktime(time.strptime(last_seen[:19], "%Y-%m-%dT%H:%M:%S")) * 1000
                if now - ls > 60_000:
                    continue
            except Exception:
                pass
        cards.append(t)
    return cards

def mem():
    try:
        return requests.get(f"{BASE}/api/v1/utils/malloc-test/", timeout=20).json()
    except Exception:
        return {}

m0 = mem()
print(f"{stamp()} BASELINE rss={m0.get('rss_before_mb')}MB threads={m0.get('threads')} plan={get_plan()}", flush=True)

# ---- Phase 1: two concurrent tasks ----
s, r = qq("帮我安装 cowsay，装完用 cowsay 输出一句你好，把输出给我看")
print(f"{stamp()} DISPATCH A(cowsay) -> {s} {r}", flush=True)
s, r = qq("帮我安装 jq，装完验证 jq --version，再用 jq 解析 {\"a\":1} 给我看")
print(f"{stamp()} DISPATCH B(jq) -> {s} {r}", flush=True)

# ---- Phase 2: chatter mid-flight ----
def chatter():
    time.sleep(20)
    s, r = qq("两个安装任务进度怎么样啦")
    print(f"{stamp()} CHATTER -> {s} {r}", flush=True)
threading.Thread(target=chatter, daemon=True).start()

# ---- Monitor ----
last_sig = None
history = []
both_seen_concurrent = 0
for i in range(300):
    time.sleep(2)
    cards = get_task_cards()
    plan = get_plan()
    sig = json.dumps([(c.get("reply_ticket_id"), [(s.get("status"), s.get("step")) for s in c.get("plan", [])]) for c in cards], ensure_ascii=False) + json.dumps(plan, ensure_ascii=False)
    if len(cards) >= 2:
        both_seen_concurrent += 1
    if sig != last_sig:
        el = time.time() - t0
        line_cards = []
        for c in cards:
            p = c.get("plan", [])
            ndone = sum(1 for s in p if s.get("status") == "completed")
            line_cards.append(f"'{str(c.get('request_message',''))[:14]}'[{c.get('ticket_status')}] {ndone}/{len(p)}")
        cur = " | ".join(f"{s.get('status')[0]}:{str(s.get('step'))[:14]}" for s in plan) if plan else "-"
        print(f"{stamp()} cards({len(cards)}): {' || '.join(line_cards) if line_cards else 'none'} | item-plan: {cur}", flush=True)
        last_sig = sig
        history.append((el, len(cards)))
    if i > 60 and not cards and not plan:
        print(f"{stamp()} plan table fully empty -> phase 1+2 settled", flush=True)
        break

# ---- Phase 3: follow-up task after table settled ----
s, r = qq("再帮我装一下 sl，装完告诉我")
print(f"{stamp()} DISPATCH C(sl follow-up) -> {s} {r}", flush=True)
last_sig = None
for i in range(150):
    time.sleep(2)
    cards = get_task_cards()
    plan = get_plan()
    sig = json.dumps([(c.get("reply_ticket_id"), [(s.get("status"), s.get("step")) for s in c.get("plan", [])]) for c in cards], ensure_ascii=False) + json.dumps(plan, ensure_ascii=False)
    if sig != last_sig:
        line_cards = []
        for c in cards:
            p = c.get("plan", [])
            ndone = sum(1 for s in p if s.get("status") == "completed")
            line_cards.append(f"'{str(c.get('request_message',''))[:14]}'[{c.get('ticket_status')}] {ndone}/{len(p)}")
        cur = " | ".join(f"{s.get('status')[0]}:{str(s.get('step'))[:14]}" for s in plan) if plan else "-"
        print(f"{stamp()} cards({len(cards)}): {' || '.join(line_cards) if line_cards else 'none'} | item-plan: {cur}", flush=True)
        last_sig = sig
    if i > 30 and not cards and not plan:
        print(f"{stamp()} follow-up settled, table empty", flush=True)
        break

m1 = mem()
print(f"\nSUMMARY: max concurrent cards={max((n for _, n in history), default=0)}, "
      f"ticks with >=2 cards={both_seen_concurrent}, "
      f"rss {m0.get('rss_before_mb')}->{m1.get('rss_before_mb')}MB threads {m0.get('threads')}->{m1.get('threads')}", flush=True)
print("[DONE]", flush=True)