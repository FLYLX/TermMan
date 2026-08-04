# -*- coding: utf-8 -*-
"""E2E: NRN finalize - job callback + no-reply should finalize ticket as completed."""
import requests, sys, io, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
LOG = r"de_bug\_mock_qq.log"
REQ = "后台跑一下 echo NRN_FINALIZE_CHECK 命令就行，不用回复我"

tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}

def totals():
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()
    return d.get("total_tokens",0), d.get("total_turns",0)

def outbox():
    return open(LOG, encoding="utf-8", errors="replace").read().splitlines()

requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=30)
t0, n0 = totals()
pre = outbox()

payload = {
    "sender_key": "private_2537134688",
    "text": REQ,
    "reply_target": {"target_type":"private","target_id":"2537134688",
        "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}},
}
t_start = time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"dispatch={r.status_code} {r.json().get('reason')}", flush=True)

last = totals(); stable = 0; seen = False
for i in range(80):
    time.sleep(3)
    cur = totals(); el = int(time.time()-t_start)
    if cur[1] > last[1]:
        print(f"[{el}s] calls {last[1]}->{cur[1]} tok+{cur[0]-t0}", flush=True); seen = True
    stable = stable+1 if (cur[0]==last[0] and seen) else 0
    last = cur
    if el > 40 and stable >= 8: break

t1, n1 = totals()
new = outbox()[len(pre):]
sends = [l for l in new if "send_private_msg" in l or "send_group_msg" in l]
print(f"\nRESULT: calls +{n1-n0} | tokens +{t1-t0} | {int(time.time()-t_start)}s", flush=True)
print(f"OUTBOX new={len(new)} SENDS={len(sends)}", flush=True)
for l in new: print("  "+l[:200], flush=True)

tasks = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage/by-task", headers=h, timeout=10).json()["tasks"]
mine = [t for t in tasks if REQ[:20] in (t.get("request_message") or "")]
print(f"\nTICKETS matching request: {len(mine)}", flush=True)
for t in mine:
    print(json.dumps({k: t.get(k) for k in ("reply_ticket_id","ticket_status","turns","total_tokens","last_seen")}, ensure_ascii=False), flush=True)
