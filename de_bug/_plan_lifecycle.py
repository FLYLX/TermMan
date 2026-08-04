# -*- coding: utf-8 -*-
"""Final lifecycle check: card appears fast with real text, then leaves the
table after delivery + 60s idle (mirrors the new frontend filter)."""
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
        terminal = all_done or status in ("delivered", "failed", "cancelled")
        if terminal and now - parse_ts(t.get("last_seen", "")) > 60_000:
            continue
        cards.append(t)
    return cards

def get_plan():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=5).json().get("plan", [])
    except Exception:
        return []

print(f"{stamp()} START plan={get_plan()} cards={len(get_cards())}", flush=True)
s, r = qq("帮我安装 bc，装完运行 echo 2+3 | bc 验证结果，把输出给我看")
print(f"{stamp()} DISPATCH(bc) -> {s} {r}", flush=True)

first_card_at = None
delivered_at = None
gone_at = None
last_sig = None
for i in range(240):
    time.sleep(2)
    cards = get_cards()
    plan = get_plan()
    if cards and first_card_at is None:
        first_card_at = time.time() - t0
    sig = json.dumps([(c.get("ticket_status"), [(s.get("status"), s.get("step")) for s in c.get("plan", [])]) for c in cards], ensure_ascii=False)
    if sig != last_sig:
        line = " || ".join(f"'{str(c.get('request_message',''))[:30]}'[{c.get('ticket_status')}] {sum(1 for s in c.get('plan',[]) if s.get('status')=='completed')}/{len(c.get('plan',[]))}" for c in cards)
        print(f"{stamp()} cards({len(cards)}): {line or 'none'} | item-plan: {len(plan)} steps", flush=True)
        last_sig = sig
    for c in cards:
        if c.get("ticket_status") == "delivered" and delivered_at is None:
            delivered_at = time.time() - t0
    if delivered_at is not None and not cards and gone_at is None:
        gone_at = time.time() - t0
        print(f"{stamp()} card removed from table (frontend view)", flush=True)
    if gone_at is not None and not plan:
        print(f"{stamp()} item-plan also empty -> fully settled", flush=True)
        break

print(f"RESULT: first_card_at={first_card_at and round(first_card_at,1)}s delivered_at={delivered_at and round(delivered_at,1)}s gone_at={gone_at and round(gone_at,1)}s", flush=True)
print("[DONE]", flush=True)