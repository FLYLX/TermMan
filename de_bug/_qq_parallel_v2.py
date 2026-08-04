# -*- coding: utf-8 -*-
"""QQ-path parallel task test v2: install python3.6 + java8 dispatched concurrently (encoding fixed)."""
import requests, time, json, threading, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT_ID = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

def qq_dispatch(msg, sender_id="2537134688", timeout=300):
    payload = {
        "sender_key": f"private_{sender_id}",
        "text": msg,
        "reply_target": {
            "target_type": "private",
            "target_id": sender_id,
            "metadata": {"sender_name": "FLY", "sender_id": sender_id, "conversation_type": "private"}
        }
    }
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/v1/robots/{ROBOT_ID}/dispatch",
                          json=payload,
                          headers={"X-Termman-Bridge-Token": BRIDGE_TOKEN},
                          timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text[:200]
        return r.status_code, body, round(time.time() - t0, 1)
    except Exception as e:
        return 0, str(e)[:200], round(time.time() - t0, 1)

token = login()
h = {"Authorization": f"Bearer {token}"}
base_tokens = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=h, timeout=10).json()
print(f"[BASELINE] tokens={base_tokens.get('total_tokens',0)} turns={base_tokens.get('total_turns',0)}", flush=True)

TASK_A = "帮我安装 Python 3.6，装完运行 python3.6 --version 验证"
TASK_B = "帮我安装 Java 8（openjdk-8-jdk），装完运行 java -version 验证"
print(f"TASK_A = {TASK_A}", flush=True)
print(f"TASK_B = {TASK_B}", flush=True)

dispatch_results = {}

def fire(name, msg, delay):
    time.sleep(delay)
    print(f"[{time.strftime('%H:%M:%S')}] DISPATCH {name}: {msg}", flush=True)
    s, body, el = qq_dispatch(msg)
    dispatch_results[name] = (s, body, el)
    snippet = json.dumps(body, ensure_ascii=False)[:250] if isinstance(body, dict) else str(body)[:250]
    print(f"[{time.strftime('%H:%M:%S')}] DISPATCH {name} returned after {el}s status={s}: {snippet}", flush=True)

tA = threading.Thread(target=fire, args=("A(py36)", TASK_A, 0))
tB = threading.Thread(target=fire, args=("B(java8)", TASK_B, 2))
tA.start(); tB.start()

def get_workflows():
    try:
        return requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=h, timeout=10).json().get("workflows", [])
    except Exception:
        return []

def get_jobs():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=h, timeout=10).json().get("jobs", [])
    except Exception:
        return []

def get_token_total():
    try:
        return requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=h, timeout=10).json().get("total_tokens", 0)
    except Exception:
        return -1

t0 = time.time()
seen_wf = {}
last_summary = ""
stable = 0
last_tok = -1
work_seen = False
for i in range(180):
    time.sleep(5)
    el = int(time.time() - t0)
    wfs = get_workflows()
    jobs = get_jobs()
    running_jobs = [j for j in jobs if j.get("status") == "running"]
    lines = []
    for w in wfs:
        wid = str(w.get("id") or w.get("workflow_id"))
        st = w.get("status", "?")
        steps = w.get("steps", [])
        ndone = sum(1 for s in steps if s.get("status") in ("completed", "cancelled", "failed"))
        if wid not in seen_wf:
            seen_wf[wid] = {"first": el, "last_active": el, "terminal": None, "title": (w.get("title") or "")[:40]}
        if st in ("running", "pending"):
            seen_wf[wid]["last_active"] = el
        elif seen_wf[wid]["terminal"] is None:
            seen_wf[wid]["terminal"] = el
        lines.append(f"{st}({ndone}/{len(steps)}) {seen_wf[wid]['title']}")
    if running_jobs or wfs:
        work_seen = True
    summary = f"[{el}s] WF: {' || '.join(lines) if lines else 'none'} | running jobs: {len(running_jobs)}"
    if summary != last_summary:
        print(summary, flush=True)
        for j in running_jobs:
            print(f"    JOB running: {str(j.get('command',''))[:90]}", flush=True)
        last_summary = summary
    active_wf = [w for w in wfs if w.get("status") in ("running", "pending")]
    tok = get_token_total()
    if tok == last_tok and not active_wf and not running_jobs and work_seen and not tA.is_alive() and not tB.is_alive():
        stable += 1
    else:
        stable = 0
    last_tok = tok
    if el > 120 and stable >= 6:
        print(f"[{el}s] state stable for 30s with no active work -> finishing monitor", flush=True)
        break

tA.join(timeout=10); tB.join(timeout=10)

print("\n" + "=" * 64, flush=True)
print("FINAL WORKFLOWS", flush=True)
wfs = get_workflows()
if not wfs:
    print("  (none)", flush=True)
for w in wfs:
    print(f"  WF {str(w.get('id'))[:8]} status={w.get('status')} title={w.get('title','')[:50]}", flush=True)
    for s in w.get("steps", []):
        print(f"    step {s.get('order')}: {s.get('title','')[:45]} [{s.get('status')}] attempts={s.get('attempts',0)}", flush=True)
    for j in w.get("jobs", []):
        print(f"    job: {str(j.get('command',''))[:70]} [{j.get('status')}] exit={j.get('exit_code')}", flush=True)

print("\nWORKFLOW TIMELINE (seconds since test start)", flush=True)
for wid, info in seen_wf.items():
    print(f"  WF {wid[:8]} '{info['title']}': first={info['first']}s last_active={info['last_active']}s terminal={info['terminal']}s", flush=True)
vals = list(seen_wf.values())
if len(vals) >= 2:
    a, b = vals[0], vals[1]
    ov_s = max(a["first"], b["first"])
    ov_e = min(a["last_active"], b["last_active"])
    print(f"  OVERLAP: {ov_s}s..{ov_e}s => {'PARALLEL (' + str(ov_e - ov_s) + 's)' if ov_e > ov_s else 'SERIAL (no overlap)'}", flush=True)

print("\nLAST SESSION MESSAGES (agent replies)", flush=True)
try:
    r = requests.get(f"{BASE}/api/v1/memory/{ITEM_ID}/session?limit=24&offset=0", headers=h, timeout=10)
    msgs = r.json().get("messages", [])
    for m in msgs:
        role = m.get("role", "?")
        if role in ("user", "assistant"):
            c = str(m.get("content", ""))[:260].replace("\n", " ")
            print(f"  [{role}] {c}", flush=True)
except Exception as e:
    print(f"  session err: {e}", flush=True)

final_tokens = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=h, timeout=10).json()
print(f"\nTokens: +{final_tokens.get('total_tokens',0)-base_tokens.get('total_tokens',0)} turns +{final_tokens.get('total_turns',0)-base_tokens.get('total_turns',0)}", flush=True)
print("\n[SCRIPT DONE]", flush=True)