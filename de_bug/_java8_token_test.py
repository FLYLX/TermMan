# -*- coding: utf-8 -*-
"""Real task token measurement: install java8 via QQ link."""
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
def jobs():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10).json().get("jobs", [])
    except Exception:
        return []
def outbox():
    return open(LOG, encoding="utf-8", errors="replace").read().splitlines()

requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=30)
print("[session cleared]", flush=True)
t0_tok, t0_turns = totals()
pre = outbox()
payload = {
    "sender_key": "private_2537134688",
    "text": "帮我安装java8，装好了告诉我",
    "reply_target": {"target_type":"private","target_id":"2537134688",
        "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}},
}
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"dispatch={r.status_code} {r.json().get('reason')}", flush=True)
last = (t0_tok, t0_turns); stable = 0; work_seen = False
for i in range(360):
    time.sleep(5)
    el = int(time.time()-t0)
    tk, tn = totals()
    js = jobs()
    running = [j for j in js if j.get("status")=="running"]
    if tn > last[1]:
        print(f"[{el}s] calls {last[1]}->{tn} tok+{tk-t0_tok} running={len(running)}", flush=True)
    elif running and i % 3 == 0:
        print(f"[{el}s] running={len(running)}: {[str(j.get('command',''))[:60] for j in running]}", flush=True)
    if running or tn > t0_turns: work_seen = True
    stable = stable+1 if (tk==last[0] and not running and work_seen) else 0
    last = (tk, tn)
    if el > 60 and stable >= 12: break
tk, tn = totals()
post = outbox(); new = post[len(pre):]
sends = [l for l in new if "send_private_msg" in l or "send_group_msg" in l]
print(f"\nRESULT java8 install: calls +{tn-t0_turns} | tokens +{tk-t0_tok} | total {int(time.time()-t0)}s", flush=True)
print(f"QQ SENDS = {len(sends)}", flush=True)
for l in sends: print("  "+l[:260], flush=True)
