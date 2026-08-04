# -*- coding: utf-8 -*-
"""Hallucination regression probe: unrelated tiny task in java8-saturated context."""
import requests, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
LOG = r"de_bug\_mock_qq.log"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
def totals():
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()
    return d.get("total_tokens",0), d.get("total_turns",0)
def outbox():
    return open(LOG, encoding="utf-8", errors="replace").read().splitlines()
# NOTE: no session clear on purpose -- keep the java8-saturated history
t0_tok, t0_turns = totals()
pre = outbox()
payload = {"sender_key":"private_2537134688","text":"后台跑一下 date 命令就行，不用回复我",
    "reply_target":{"target_type":"private","target_id":"2537134688",
        "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}}}
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"dispatch={r.status_code} {r.json().get('reason')}", flush=True)
last = totals(); stable = 0; seen = False
for i in range(100):
    time.sleep(4)
    cur = totals(); el = int(time.time()-t0)
    if cur[1] > last[1]: print(f"[{el}s] calls {last[1]}->{cur[1]} tok+{cur[0]-t0_tok}", flush=True); seen = True
    stable = stable+1 if (cur[0]==last[0] and seen) else 0
    last = cur
    if el > 30 and stable >= 8: break
tk, tn = totals()
sends = [l for l in outbox()[len(pre):] if "send_private_msg" in l]
print(f"\nRESULT: calls +{tn-t0_turns} | tokens +{tk-t0_tok} | sends={len(sends)}", flush=True)
for l in sends: print("  "+l[:200], flush=True)
