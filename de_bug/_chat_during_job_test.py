# -*- coding: utf-8 -*-
"""Verify: chat during long job gets its own immediate turn."""
import requests, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
LOG = r"de_bug\_mock_qq.log"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
def outbox():
    return open(LOG, encoding="utf-8", errors="replace").read().splitlines()
requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=30)
pre = outbox()
def dispatch(text):
    payload = {"sender_key":"private_2537134688","text":text,
        "reply_target":{"target_type":"private","target_id":"2537134688",
            "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}}}
    r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
    return r.status_code, r.json().get("reason")

t0 = time.time()
sc, reason1 = dispatch("帮我后台跑个任务：sleep 60 && echo LONG_JOB_DONE，完成后告诉我")
print(f"[{int(time.time()-t0)}s] job dispatch={sc} reason={reason1}", flush=True)
time.sleep(10)
sc, reason2 = dispatch("1加1等于？直接回答数字")
print(f"[{int(time.time()-t0)}s] chat dispatch={sc} reason={reason2}", flush=True)
chat_answered_at = None; job_reported_at = None
for i in range(120):
    time.sleep(3)
    el = int(time.time()-t0)
    new = outbox()[len(pre):]
    sends = [l for l in new if "send_private_msg" in l]
    if chat_answered_at is None and any("2" in l.split(":")[-1] for l in sends):
        for l in sends:
            if "2" in l.split(":")[-1] and "LONG_JOB" not in l:
                chat_answered_at = el; print(f"[{el}s] CHAT ANSWERED: {l[:120]}", flush=True); break
    if job_reported_at is None and any("LONG_JOB_DONE" in l or ("完成" in l and "60" in l) for l in sends):
        job_reported_at = el; print(f"[{el}s] JOB REPORTED", flush=True)
    if chat_answered_at and job_reported_at: break
    if el > 30 and chat_answered_at is None and i % 5 == 0:
        print(f"[{el}s] waiting... sends={len(sends)}", flush=True)
print(f"\nRESULT: chat answered at {chat_answered_at}s | job reported at {job_reported_at}s", flush=True)
for l in outbox()[len(pre):]:
    if "send_" in l: print("  "+l[:220], flush=True)
