# -*- coding: utf-8 -*-
"""Adaptability test: slow install + mid-task domestic mirror switch."""
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
def dispatch(text):
    payload = {"sender_key":"private_2537134688","text":text,
        "reply_target":{"target_type":"private","target_id":"2537134688",
            "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}}}
    r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
    return r.status_code, r.json().get("reason")

requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=30)
t0_tok, t0_turns = totals()
pre = outbox()
t0 = time.time()
sc, reason = dispatch("帮我安装java8，装好了告诉我")
print(f"[{int(time.time()-t0)}s] install dispatch={sc} reason={reason}", flush=True)
time.sleep(75)
sc, reason = dispatch("换个国内镜像吧，国外源太慢了")
print(f"[{int(time.time()-t0)}s] mirror dispatch={sc} reason={reason}", flush=True)
last = (t0_tok, t0_turns); stable = 0; done_at = None
for i in range(480):
    time.sleep(5)
    el = int(time.time()-t0)
    tk, tn = totals()
    sends = [l for l in outbox()[len(pre):] if "send_private_msg" in l]
    final = [l for l in sends if ("java" in l.lower() or "Java" in l or "装" in l or "安装" in l)]
    if tn > last[1]:
        print(f"[{el}s] calls {last[1]}->{tn} tok+{tk-t0_tok} sends={len(sends)}", flush=True)
    last = (tk, tn)
    if final and done_at is None:
        done_at = el
        print(f"[{el}s] FINAL REPORT: {final[-1][:200]}", flush=True)
    if done_at is not None and el > done_at + 30: break
    if el > 2100: print("[2100s] hard stop", flush=True); break
tk, tn = totals()
sends = [l for l in outbox()[len(pre):] if "send_private_msg" in l]
print(f"\nRESULT: calls +{tn-t0_turns} | tokens +{tk-t0_tok} | total {int(time.time()-t0)}s | sends={len(sends)}", flush=True)
for l in sends: print("  "+l[:240], flush=True)
