# -*- coding: utf-8 -*-
"""Measure token usage of ONE plain chat turn via QQ link (clean session)."""
import requests, sys, io, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

tok = requests.post(f"{BASE}/api/v1/login/access-token",
                    data={"username": "admin@example.com", "password": "changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}

def totals():
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()
    return d.get("total_prompt_tokens", 0), d.get("total_completion_tokens", 0), d.get("total_tokens", 0), d.get("total_turns", 0)

def tasks():
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage/by-task", headers=h, timeout=10).json()
    return d if isinstance(d, list) else d.get("tasks", d.get("items", []))

# 1) clean session for a fresh measurement
r = requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=30)
print(f"[clear session] status={r.status_code}", flush=True)

p0, c0, t0, n0 = totals()
print(f"[baseline] prompt={p0} completion={c0} total={t0} llm_calls={n0}", flush=True)
known_tickets = {t.get("reply_ticket_id") for t in tasks()} if True else set()

# 2) one plain chat message (no tools expected)
MSG = "1加1等于几？直接回答数字就行，不用做任何其他事情"
payload = {
    "sender_key": "private_2537134688",
    "text": MSG,
    "reply_target": {
        "target_type": "private",
        "target_id": "2537134688",
        "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"},
    },
}
t_start = time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
                  headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"[{time.strftime('%H:%M:%S')}] dispatch status={r.status_code} body={r.text[:120]}", flush=True)

last = totals()
stable = 0
seen = False
for i in range(100):
    time.sleep(3)
    el = int(time.time() - t_start)
    cur = totals()
    if cur[3] > last[3]:
        print(f"[{el}s] llm_calls {last[3]}->{cur[3]} total_tok={cur[2]}", flush=True)
        seen = True
    if cur[2] == last[2] and seen:
        stable += 1
    else:
        stable = 0
    last = cur
    if el > 20 and stable >= 8:
        print(f"[{el}s] stable 24s -> done", flush=True)
        break

p1, c1, t1, n1 = totals()
print(f"\n=== ONE-TURN CHAT RESULT ===", flush=True)
print(f"llm_calls +{n1-n0} | prompt +{p1-p0} | completion +{c1-c0} | total +{t1-t0} | elapsed {int(time.time()-t_start)}s", flush=True)

# 3) per-task breakdown: find the new ticket
try:
    for t in tasks():
        if t.get("reply_ticket_id") not in known_tickets:
            print(f"\n[by-task] ticket={str(t.get('reply_ticket_id'))[:8]} status={t.get('ticket_status')} turns={t.get('turns')} prompt={t.get('prompt_tokens')} completion={t.get('completion_tokens')} total={t.get('total_tokens')}", flush=True)
            print(f"          request={str(t.get('request_message'))[:60]}", flush=True)
except Exception as e:
    print(f"[by-task] err {e}", flush=True)

print("\nMOCK QQ OUTBOX (last 3)", flush=True)
for l in open(r"de_bug\_mock_qq.log", encoding="utf-8", errors="replace").read().splitlines()[-3:]:
    print("  " + l[:220], flush=True)
print("[DONE]", flush=True)
