# -*- coding: utf-8 -*-
"""Busy-merge test: QQ dispatch 3 background sleep jobs (5/12/14s), watch turn count."""
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
    try:
        d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()
        return d.get("total_tokens", 0), d.get("total_turns", 0)
    except Exception:
        return -1, -1

def jobs():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10).json().get("jobs", [])
    except Exception:
        return []

t0_tok, t0_turns = tokens()
print(f"baseline tokens={t0_tok} turns={t0_turns}", flush=True)

MSG = ("帮我并行跑3个后台任务（必须都用run_job后台任务派发，不要用execute_command）："
       "1) sleep 5 && echo JOB_A_DONE  "
       "2) sleep 12 && echo JOB_B_DONE  "
       "3) sleep 14 && echo JOB_C_DONE。"
       "派发完先简短回我一句。任务完成时你会收到结果通知，注意汇总。")

payload = {
    "sender_key": "private_2537134688",
    "text": MSG,
    "reply_target": {
        "target_type": "private",
        "target_id": "2537134688",
        "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"},
    },
}
ts = time.strftime("%H:%M:%S")
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
                  headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"[{ts}] dispatch status={r.status_code} body={json.dumps(r.json(), ensure_ascii=False)[:200]}", flush=True)

t0 = time.time()
last = (t0_tok, t0_turns)
stable = 0
work_seen = False
turn_marks = []
for i in range(200):
    time.sleep(5)
    el = int(time.time() - t0)
    tk, tn = tokens()
    js = jobs()
    running = [j for j in js if j.get("status") == "running"]
    if tn > last[1]:
        turn_marks.append((el, tn, tk - t0_tok))
        print(f"[{el}s] TURNS {last[1]}->{tn} (tokens +{tk - t0_tok}) running_jobs={len(running)}", flush=True)
    elif running:
        print(f"[{el}s] turns={tn} running_jobs={len(running)}: {[str(j.get('command',''))[:40] for j in running]}", flush=True)
    if running or tn > t0_turns:
        work_seen = True
    if tk == last[0] and not running and work_seen:
        stable += 1
    else:
        stable = 0
    last = (tk, tn)
    if el > 60 and stable >= 12:
        print(f"[{el}s] stable 60s -> done monitoring", flush=True)
        break

tk, tn = tokens()
print(f"\nRESULT: turns +{tn - t0_turns}, tokens +{tk - t0_tok}", flush=True)
print("turn timeline:", turn_marks, flush=True)

print("\nLAST SESSION MESSAGES", flush=True)
try:
    r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=30&offset=0", headers=h, timeout=10)
    for m in r.json().get("messages", []):
        role = m.get("role", "?")
        if role in ("user", "assistant"):
            c = str(m.get("content", ""))[:220].replace("\n", " ")
            print(f"  [{role}] {c}", flush=True)
except Exception as e:
    print("  err", e, flush=True)

print("\nMOCK QQ OUTBOX (last 15 lines)", flush=True)
try:
    lines = open(r"de_bug\_mock_qq.log", encoding="utf-8", errors="replace").read().splitlines()
    for l in lines[-15:]:
        print("  " + l[:220], flush=True)
except Exception as e:
    print("  err", e, flush=True)
print("[SCRIPT DONE]", flush=True)
