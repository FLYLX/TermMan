# -*- coding: utf-8 -*-
"""Idle single-job test: confirm zero-delay immediate turn for idle conversation."""
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

tok = requests.post(f"{BASE}/api/v1/login/access-token",
                    data={"username": "admin@example.com", "password": "changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}

def tokens():
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()
    return d.get("total_tokens", 0), d.get("total_turns", 0)

t0_tok, t0_turns = tokens()
MSG = "帮我后台跑一个任务：sleep 5 && echo IDLE_MERGE_OK，完成后汇报结果"
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
print(f"[{time.strftime('%H:%M:%S')}] dispatch status={r.status_code} reason={r.json().get('reason')}", flush=True)

last = (t0_tok, t0_turns)
stable = 0
seen = False
for i in range(100):
    time.sleep(3)
    el = int(time.time() - t_start)
    tk, tn = tokens()
    if tn > last[1]:
        print(f"[{el}s] TURNS {last[1]}->{tn} (+{tk - t0_tok} tok)", flush=True)
        seen = True
    if tk == last[0] and seen:
        stable += 1
    else:
        stable = 0
    last = (tk, tn)
    if el > 30 and stable >= 10:
        print(f"[{el}s] stable 30s -> done", flush=True)
        break

tk, tn = tokens()
print(f"RESULT: turns(llm calls) +{tn - t0_turns}, tokens +{tk - t0_tok}, elapsed {int(time.time()-t_start)}s", flush=True)
print("\nMOCK QQ OUTBOX (last 3)", flush=True)
for l in open(r"de_bug\_mock_qq.log", encoding="utf-8", errors="replace").read().splitlines()[-3:]:
    print("  " + l[:200], flush=True)
print("[DONE]", flush=True)
