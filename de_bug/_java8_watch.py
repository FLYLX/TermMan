# -*- coding: utf-8 -*-
"""Continue monitoring the java8 install until the callback report lands."""
import requests, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"de_bug\_mock_qq.log"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
def totals():
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()
    return d.get("total_tokens",0), d.get("total_turns",0)
def outbox():
    return open(LOG, encoding="utf-8", errors="replace").read().splitlines()
base_tok, base_calls = totals()
start_sends = len([l for l in outbox() if "send_" in l])
t0 = time.time()
last = (base_tok, base_calls); stable = 0
for i in range(240):
    time.sleep(5)
    el = int(time.time()-t0)
    tk, tn = totals()
    sends_now = len([l for l in outbox() if "send_" in l])
    if tn > last[1] or sends_now > start_sends:
        print(f"[{el}s] calls {base_calls}->{tn} tok+{tk-base_tok} sends+{sends_now-start_sends}", flush=True)
        stable = 0
    else:
        stable += 1
    last = (tk, tn)
    if stable >= 24 and sends_now > start_sends:
        print(f"[{el}s] report delivered + 120s quiet -> done", flush=True)
        break
    if stable >= 60:
        print(f"[{el}s] 300s quiet, no report -> stopping", flush=True)
        break
tk, tn = totals()
print(f"\nTOTAL since dispatch baseline: calls now {tn} | tokens now {tk}", flush=True)
print("last outbox lines:", flush=True)
for l in outbox()[-4:]: print("  "+l[:260], flush=True)
