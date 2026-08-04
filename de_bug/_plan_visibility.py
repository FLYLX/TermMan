# -*- coding: utf-8 -*-
"""Plan visibility test: dispatch multi-step task via QQ, poll plan API every 1s."""
import requests, json, sys, io, time, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

token = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

def get_plan():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=5).json()
    except Exception as e:
        return {"error": str(e)[:60]}

def get_tasks():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage-by-task", headers=h, timeout=5).json()
    except Exception:
        try:
            return requests.get(f"{BASE}/api/v1/items/{ITEM}/token-by-task", headers=h, timeout=5).json()
        except Exception as e:
            return {"error": str(e)[:60]}

# baseline
p0 = get_plan()
print(f"[T-0] baseline plan: {json.dumps(p0, ensure_ascii=False)[:150]}", flush=True)
t0 = time.time()

def stamp():
    return f"[{time.time()-t0:6.1f}s]"

# dispatch planning task via QQ
msg = "帮我按顺序做三件事并做个计划：1. 查看系统时间 2. 查看磁盘使用情况 3. 查看内存使用情况，每做完一步就汇报"
payload = {
    "sender_key": "private_2537134688",
    "text": msg,
    "reply_target": {"target_type": "private", "target_id": "2537134688",
                     "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"}}
}
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload,
                  headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=30)
print(f"{stamp()} dispatch -> {r.status_code} {r.json().get('reason')}", flush=True)

# poll plan every 1s for up to 4 min, log state changes
last = None
seen_first_plan = None
plan_gone = None
steps_log = []
for i in range(240):
    time.sleep(1)
    d = get_plan()
    plan = d.get("plan", []) if isinstance(d, dict) else []
    sig = json.dumps(plan, ensure_ascii=False)
    if plan and seen_first_plan is None:
        seen_first_plan = time.time() - t0
    if not plan and seen_first_plan is not None and plan_gone is None:
        plan_gone = time.time() - t0
    if sig != last:
        el = time.time() - t0
        if plan:
            desc = " | ".join(f"{s.get('status','?')}:{str(s.get('step',''))[:22]}" for s in plan)
            print(f"{stamp()} PLAN({len(plan)}): {desc}", flush=True)
        else:
            print(f"{stamp()} PLAN: (empty)", flush=True)
        last = sig
    if plan_gone is not None and time.time() - t0 > plan_gone + 5:
        break

print(f"\nSUMMARY: plan first visible at {seen_first_plan and round(seen_first_plan,1)}s, "
      f"cleared at {plan_gone and round(plan_gone,1)}s", flush=True)

# task-level plans (token-by-task)
tk = get_tasks()
print(f"token-by-task keys: {list(tk.keys()) if isinstance(tk, dict) else tk}", flush=True)
tasks = tk.get("tasks", []) if isinstance(tk, dict) else []
for t in tasks[-3:]:
    tp = t.get("plan", [])
    print(f"  task '{str(t.get('request_message',''))[:30]}' status={t.get('ticket_status')} plan_steps={len(tp)}", flush=True)
    for s in tp:
        print(f"    - [{s.get('status')}] {str(s.get('step',''))[:40]}", flush=True)
print("[DONE]", flush=True)