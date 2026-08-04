# -*- coding: utf-8 -*-
"""Targeted: two concurrent tasks, no chatter. Verifies the pending-batch
structured request_message path (task B is deferred, then drained)."""
import requests, json, sys, io, time
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

def qq(msg):
    payload = {"sender_key": f"private_{SENDER}", "text": msg,
               "reply_target": {"target_type": "private", "target_id": SENDER,
                                "metadata": {"sender_name": "FLY", "sender_id": SENDER, "conversation_type": "private"}}}
    r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
                      headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
    return r.status_code, (r.json().get("reason") if r.ok else r.text[:80])

def parse_ts(ts):
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")) * 1000
    except Exception:
        return 0

def get_cards():
    """Mirror of frontend PlanPanel tasksWithPlans filter."""
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
        status = t.get("ticket_status", "")
        all_done = all(s.get("status") == "completed" for s in plan)
        stale_terminal = (all_done or status in ("failed", "cancelled"))
        if stale_terminal and now - parse_ts(t.get("last_seen", "")) > 60_000:
            continue
        cards.append(t)
    return cards

def get_plan():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=5).json().get("plan", [])
    except Exception:
        return []

print(f"{stamp()} START", flush=True)
s, r = qq("帮我用 apt 安装 tree，装完运行 tree --version 验证，把结果给我看")
print(f"{stamp()} DISPATCH A(tree) -> {s} {r}", flush=True)
time.sleep(0.3)
s, r = qq("再帮我安装 figlet，装完运行 figlet hello 验证，把结果给我看")
print(f"{stamp()} DISPATCH B(figlet) -> {s} {r}", flush=True)

last_sig = None
seen_b_card = False
b_title_ok = False
for i in range(300):
    time.sleep(2)
    cards = get_cards()
    plan = get_plan()
    sig = json.dumps([(c.get("reply_ticket_id"), c.get("ticket_status"), [(s.get("status"), s.get("step")) for s in c.get("plan", [])]) for c in cards], ensure_ascii=False) + json.dumps(plan, ensure_ascii=False)
    for c in cards:
        rm = str(c.get("request_message", ""))
        if "figlet" in rm:
            seen_b_card = True
            if not rm.lstrip().startswith("[Pending QQ messages"):
                b_title_ok = True
    if sig != last_sig:
        line = " || ".join(f"'{str(c.get('request_message',''))[:26]}'[{c.get('ticket_status')}] {sum(1 for s in c.get('plan',[]) if s.get('status')=='completed')}/{len(c.get('plan',[]))}" for c in cards)
        cur = " | ".join(f"{s.get('status')[0]}:{str(s.get('step'))[:12]}" for s in plan) if plan else "-"
        print(f"{stamp()} cards({len(cards)}): {line or 'none'} | item-plan: {cur}", flush=True)
        last_sig = sig
    if i > 30 and not cards and not plan:
        print(f"{stamp()} table empty -> settled", flush=True)
        break

print(f"RESULT: seen_b_card={seen_b_card} b_title_is_real_text={b_title_ok}", flush=True)
print("[DONE]", flush=True)