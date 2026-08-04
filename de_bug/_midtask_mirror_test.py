# -*- coding: utf-8 -*-
"""Mid-task control message: switch to domestic mirror while install 'running'."""
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
t0_tok, t0_turns = totals()
pre = outbox()
payload = {
    "sender_key": "private_2537134688",
    "text": "换个国内镜像吧，国外源太慢了",
    "reply_target": {"target_type":"private","target_id":"2537134688",
        "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}},
}
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
j = r.json()
print(f"dispatch={r.status_code} reason={j.get('reason')}", flush=True)
last = (t0_tok, t0_turns); stable = 0; seen = False
for i in range(160):
    time.sleep(5)
    el = int(time.time()-t0)
    tk, tn = totals()
    sends_now = len([l for l in outbox() if "send_" in l]) - len([l for l in pre if "send_" in l])
    if tn > last[1]:
        print(f"[{el}s] calls {last[1]}->{tn} tok+{tk-t0_tok} sends+{sends_now}", flush=True)
        seen = True
    stable = stable+1 if (tk==last[0] and seen) else 0
    last = (tk, tn)
    if el > 30 and stable >= 12: break
tk, tn = totals()
post = outbox(); new = post[len(pre):]
sends = [l for l in new if "send_private_msg" in l or "send_group_msg" in l]
print(f"\nRESULT: calls +{tn-t0_turns} | tokens +{tk-t0_tok} | {int(time.time()-t0)}s | SENDS={len(sends)}", flush=True)
for l in sends: print("  "+l[:260], flush=True)
