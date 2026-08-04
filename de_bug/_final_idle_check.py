# -*- coding: utf-8 -*-
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
payload = {
    "sender_key": "private_2537134688",
    "text": "在吗？回我一句就行",
    "reply_target": {
        "target_type": "private",
        "target_id": "2537134688",
        "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"},
    },
}
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
                  headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"dispatch reason={r.json().get('reason')} ({round(time.time()-t0,1)}s)", flush=True)
time.sleep(45)
lines = open(r"de_bug\_mock_qq.log", encoding="utf-8", errors="replace").read().splitlines()
print("QQ outbox last 2:", flush=True)
for l in lines[-2:]:
    print("  " + l[:160], flush=True)
