# -*- coding: utf-8 -*-
"""Multi-entry stress test: 2 QQ private users + 1 QQ group + web chat, same item.
Verifies: reply delivery per conversation, plan behavior, task conflict handling."""
import requests, json, sys, io, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
USER_A = "2537134688"      # FLY private
USER_B = "1234509876"      # second private user
GROUP  = "777666"          # group id
BOT_QQ = "10001"

tok = requests.post(f"{BASE}/api/v1/login/access-token",
                    data={"username": "admin@example.com", "password": "changethis"}, timeout=10).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}

def tokens():
    try:
        d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=H, timeout=10).json()
        return d.get("total_tokens", 0), d.get("total_turns", 0)
    except Exception:
        return -1, -1

def jobs():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=H, timeout=10).json().get("jobs", [])
    except Exception:
        return []

def plan():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=H, timeout=10).json()
    except Exception:
        return {}

def qq(text, target_type, target_id, sender_id, sender_name, mentioned=False):
    payload = {
        "sender_key": f"{target_type}_{target_id}_{sender_id}",
        "text": text,
        "reply_target": {
            "target_type": target_type,
            "target_id": str(target_id),
            "metadata": {
                "sender_name": sender_name, "sender_id": str(sender_id),
                "conversation_type": target_type,
                **({"mentioned_bot": True} if mentioned else {}),
            },
        },
    }
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
                          headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
        return r.status_code, (r.json() or {}).get("reason"), round(time.time() - t0, 1)
    except Exception as e:
        return 0, str(e)[:80], round(time.time() - t0, 1)

def web(message):
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": message, "history": []},
                          headers=H, timeout=300)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return r.status_code, body, round(time.time() - t0, 1)
    except Exception as e:
        return 0, {"error": str(e)[:120]}, round(time.time() - t0, 1)

# mark mock QQ log position
LOG = r"de_bug\_mock_qq.log"
log_start = len(open(LOG, encoding="utf-8", errors="replace").read().splitlines())

t0_tok, t0_turns = tokens()
print(f"baseline tokens={t0_tok} turns={t0_turns}", flush=True)

results = {}
def fire(name, fn):
    out = fn()
    results[name] = out
    print(f"[{time.strftime('%H:%M:%S')}] DISPATCH {name} -> {str(out)[:160]}", flush=True)

TASK_A = f"帮我后台跑一个任务（用run_job）：sleep 8 && echo STRESS_A_DONE，完成后汇报结果"
TASK_B = f"帮我后台跑一个任务（用run_job）：sleep 14 && echo STRESS_B_DONE，完成后汇报结果"
TASK_G = f"[CQ:at,qq={BOT_QQ}] 帮我后台跑一个任务（用run_job）：sleep 11 && echo STRESS_GROUP_DONE，完成后汇报结果"
TASK_W = f"后台运行 sleep 9 && echo STRESS_WEB_DONE（run_job），完成后汇报"

threads = [
    threading.Thread(target=fire, args=("A-private", lambda: qq(TASK_A, "private", USER_A, USER_A, "FLY"))),
    threading.Thread(target=fire, args=("B-private", lambda: qq(TASK_B, "private", USER_B, USER_B, "小明"))),
    threading.Thread(target=fire, args=("G-group",   lambda: qq(TASK_G, "group", GROUP, USER_A, "FLY", mentioned=True))),
    threading.Thread(target=fire, args=("W-web",     lambda: web(TASK_W))),
]
t_start = time.time()
for i, th in enumerate(threads):
    th.start()
    time.sleep(0.8)

def chat_b():
    time.sleep(6)
    print(f"[{time.strftime('%H:%M:%S')}] CHAT B-private: 3+4=?", flush=True)
    print("   ->", qq(f"3+4等于？只回数字", "private", USER_B, USER_B, "小明"), flush=True)
def chat_g():
    time.sleep(8)
    print(f"[{time.strftime('%H:%M:%S')}] CHAT G-group: 9-2=?", flush=True)
    print("   ->", qq(f"[CQ:at,qq={BOT_QQ}] 9-2等于？只回数字", "group", GROUP, USER_A, "FLY", mentioned=True), flush=True)
threading.Thread(target=chat_b).start()
threading.Thread(target=chat_g).start()

plan_snaps = []
last = (t0_tok, t0_turns)
stable = 0
seen_work = False
last_plan_sig = None
for i in range(130):
    time.sleep(5)
    el = int(time.time() - t_start)
    tk, tn = tokens()
    js = jobs()
    running = [j for j in js if j.get("status") == "running"]
    p = plan()
    steps = p.get("plan") or p.get("steps") or []
    sig = json.dumps(steps, ensure_ascii=False)
    if sig != last_plan_sig:
        last_plan_sig = sig
        brief = " | ".join(f"{s.get('status','?')}:{str(s.get('step',''))[:26]}" for s in steps) if steps else "(empty)"
        plan_snaps.append((el, brief))
        print(f"[{el}s] PLAN -> {brief}", flush=True)
    if tn > last[1]:
        print(f"[{el}s] TURNS {last[1]}->{tn} (+{tk-t0_tok} tok) running_jobs={len(running)}", flush=True)
    if running or tn > t0_turns:
        seen_work = True
    if tk == last[0] and not running and seen_work:
        stable += 1
    else:
        stable = 0
    last = (tk, tn)
    if el > 90 and stable >= 12:
        print(f"[{el}s] stable 60s -> done", flush=True)
        break

tk, tn = tokens()
print(f"\nRESULT: turns(llm)+{tn-t0_turns} tokens+{tk-t0_tok} elapsed={int(time.time()-t_start)}s", flush=True)

print("\n=== MOCK QQ OUTBOX (new lines, grouped by target) ===", flush=True)
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()[log_start:]
by_target = {}
for l in lines:
    if "QQ [send" in l:
        by_target.setdefault("ALL", []).append(l)
        for tgt in (f"-> {USER_A}:", f"-> {USER_B}:", f"-> {GROUP}:"):
            if tgt in l:
                by_target.setdefault(tgt, []).append(l)
for tgt, ls in by_target.items():
    print(f"\n[{tgt}] {len(ls)} send(s)", flush=True)
    for l in ls:
        print("   " + l[:190], flush=True)

print("\n=== CROSS-TALK MATRIX (which STRESS marker appears in which target's sends) ===", flush=True)
markers = ["STRESS_A", "STRESS_B", "STRESS_GROUP", "STRESS_WEB"]
for tgt in (f"-> {USER_A}:", f"-> {USER_B}:", f"-> {GROUP}:"):
    text = "\n".join(by_target.get(tgt, []))
    hit = [m for m in markers if m in text]
    print(f"  {tgt} markers={hit}", flush=True)

print("\n=== SESSION: assistant messages mentioning STRESS_/reports ===", flush=True)
try:
    r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=80&offset=0", headers=H, timeout=15)
    msgs = r.json().get("messages", [])
    for m in reversed(msgs):
        c = str(m.get("content", ""))
        role = m.get("role")
        if role == "assistant" and ("STRESS_" in c or "已回复" in c):
            print(f"  [{role}] {c[:200].replace(chr(10),' ')}", flush=True)
except Exception as e:
    print("  err", e, flush=True)

print("\n=== FINAL WORKFLOWS ===", flush=True)
try:
    wf = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=H, timeout=10).json()
    for w in wf.get("workflows", [])[:8]:
        print(f"  [{w.get('status')}] {str(w.get('title',''))[:60]}", flush=True)
except Exception as e:
    print("  err", e, flush=True)

print(f"\nFINAL PLAN: {last_plan_sig}", flush=True)
print("[SCRIPT DONE]", flush=True)
