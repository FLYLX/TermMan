# -*- coding: utf-8 -*-
"""Complex-task plan timeliness test: dispatch a multi-step task and poll the
exact endpoint the frontend plan panel uses (token-usage/by-task), logging
every plan-state change with timestamps."""
import requests, time, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ROBOT_ID = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

TASK = ("帮我完成一组任务并汇报：1) 创建目录 /tmp/plan_stress2 并在里面写文件 a.txt 内容 alpha；"
        "2) 再写文件 b.txt 内容 beta；3) 把两个文件合并成 c.txt；4) 读取 c.txt 内容并告诉我结果。"
        "每一步做完再继续下一步。")

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def fetch_tasks(h):
    try:
        r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage/by-task", headers=h, timeout=10)
        return r.json().get("tasks", [])
    except Exception as e:
        return [{"error": str(e)}]

def frontend_visible(tasks):
    # mirror frontend tasksWithPlans filter (60s idle rule for terminal tasks)
    now_ms = time.time() * 1000
    visible = []
    for t in tasks:
        plan = t.get("plan") or []
        if not plan:
            continue
        all_done = all(s.get("status") == "completed" for s in plan)
        terminal = all_done or t.get("ticket_status") in ("delivered", "failed", "cancelled")
        last_seen = t.get("last_seen")
        if terminal and last_seen:
            try:
                from datetime import datetime
                ls = datetime.fromisoformat(last_seen.replace("Z", "+00:00")).timestamp() * 1000
                if now_ms - ls > 60_000:
                    continue
            except Exception:
                pass
        visible.append(t)
    return visible

def plan_signature(t):
    return tuple((s.get("title", "")[:20], s.get("status")) for s in (t.get("plan") or []))

h = login()
print("[BASELINE] tasks with plans:", [t.get("task_id", "?")[:8] for t in frontend_visible(fetch_tasks(h))], flush=True)

payload = {
    "sender_key": "private_2537134688",
    "text": TASK,
    "reply_target": {
        "target_type": "private",
        "target_id": "2537134688",
        "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"},
    },
}
t0 = time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT_ID}/dispatch", json=payload,
                  headers={"X-Termman-Bridge-Token": BRIDGE_TOKEN}, timeout=30)
print(f"[{time.time()-t0:6.1f}s] DISPATCH -> {r.status_code} {r.text[:100]}", flush=True)

first_plan_at = None
last_sig = None
last_status = None
delivered_at = None
timeline = []
deadline = time.time() + 480

while time.time() < deadline:
    time.sleep(2)
    el = time.time() - t0
    tasks = fetch_tasks(h)
    visible = frontend_visible(tasks)
    for t in visible:
        sig = plan_signature(t)
        status = t.get("ticket_status")
        if first_plan_at is None and sig:
            first_plan_at = el
            print(f"[{el:6.1f}s] PLAN APPEARED in frontend view ({len(sig)} steps), ticket={status}", flush=True)
            for step_title, step_status in sig:
                print(f"          - [{step_status}] {step_title}", flush=True)
            last_sig = sig
        elif sig != last_sig:
            print(f"[{el:6.1f}s] PLAN CHANGED (ticket={status}):", flush=True)
            for step_title, step_status in sig:
                print(f"          - [{step_status}] {step_title}", flush=True)
            last_sig = sig
        if status != last_status:
            print(f"[{el:6.1f}s] ticket_status: {last_status} -> {status}", flush=True)
            last_status = status
        if status == "delivered" and delivered_at is None:
            delivered_at = el
    if delivered_at is not None and time.time() - t0 > delivered_at + 75:
        # check whether it left the frontend view (60s idle rule)
        still = frontend_visible(fetch_tasks(h))
        print(f"[{time.time()-t0:6.1f}s] post-delivery check: still visible in plan panel = {bool(still)}", flush=True)
        break

print("\n[SUMMARY]", flush=True)
print(f"  dispatch -> plan visible: {first_plan_at:.1f}s" if first_plan_at else "  plan NEVER appeared", flush=True)
print(f"  dispatch -> delivered: {delivered_at:.1f}s" if delivered_at else "  NOT delivered within deadline", flush=True)
print("[SCRIPT DONE]", flush=True)