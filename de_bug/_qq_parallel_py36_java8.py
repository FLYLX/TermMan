# -*- coding: utf-8 -*-
"""QQ-path parallel task test: install python3.6 + java8 dispatched concurrently."""
import requests, time, json, threading, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
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
        r = requests.post(f"{BASE}/api/v1/robots/5cbc7f55-04a2-40f6-900a-05e0b0dd652a/dispatch",
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
print(f"[BASELINE] tokens={base_tokens.get('total_tokens',0)} turns={base_tokens.get('total_turns',0)}")

TASK_A = "???? Python 3.6????? python3.6 --version ??"
TASK_B = "???? Java 8?openjdk-8-jdk?????? java -version ??"

dispatch_results = {}

def fire(name, msg, delay):
    time.sleep(delay)
    print(f"[{time.strftime('%H:%M:%S')}] DISPATCH {name}: {msg}", flush=True)
    s, body, el = qq_dispatch(msg)
    dispatch_results[name] = (s, body, el)
    print(f"[{time.strftime('%H:%M:%S')}] DISPATCH {name} returned after {el}s status={s}: {json.dumps(body, ensure_ascii=False)[:200] if isinstance(body, dict) else str(body)[:200]}", flush=True)

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

# monitor up to 15 min
t0 = time.time()
seen = {}   # workflow_id -> dict(first_seen, last_active, terminal_at)
last_summary = ""
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
        if wid not in seen:
            seen[wid] = {"first": el, "last_active": el, "terminal": None, "title": w.get("title", "")[:40]}
        if st in ("running", "pending"):
            seen[wid]["last_active"] = el
        elif seen[wid]["terminal"] is None:
            seen[wid]["terminal"] = el
        lines.append(f"{st}({ndone}/{len(steps)}) {seen[wid]['title']}")
    summary = f"[{el}s] WF: {' || '.join(lines) if lines else 'none'} | running jobs: {len(running_jobs)}"
    if summary != last_summary:
        print(summary, flush=True)
        for j in running_jobs:
            print(f"    JOB running: {str(j.get('command',''))[:80]}", flush=True)
        last_summary = summary
    active = [w for w in wfs if w.get("status") in ("running", "pending")]
    if not active and el > 30 and not tA.is_alive() and not tB.is_alive():
        print(f"[{el}s] all workflows terminal and dispatches returned", flush=True)
        break

tA.join(timeout=10); tB.join(timeout=10)

print("\n" + "=" * 64)
print("FINAL WORKFLOWS")
wfs = get_workflows()
for w in wfs:
    print(f"  WF {str(w.get('id'))[:8]} status={w.get('status')} title={w.get('title','')[:50]}")
    for s in w.get("steps", []):
        print(f"    step {s.get('order')}: {s.get('title','')[:45]} [{s.get('status')}] attempts={s.get('attempts',0)}")
    for j in w.get("jobs", []):
        print(f"    job: {str(j.get('command',''))[:70]} [{j.get('status')}] exit={j.get('exit_code')}")

print("\nPARALLELISM TIMELINE (seconds since test start)")
for wid, info in seen.items():
    print(f"  WF {wid[:8]} '{info['title']}': first_seen={info['first']}s last_active={info['last_active']}s terminal={info['terminal']}s")
ids = list(seen.values())
if len(ids) >= 2:
    a, b = ids[0], ids[1]
    overlap_start = max(a["first"], b["first"])
    overlap_end = min(a["last_active"], b["last_active"])
    print(f"  OVERLAP window: {overlap_start}s..{overlap_end}s => {'PARALLEL (' + str(overlap_end-overlap_start) + 's)' if overlap_end > overlap_start else 'SERIAL (no overlap)'}")

final_tokens = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=h, timeout=10).json()
print(f"\nTokens: +{final_tokens.get('total_tokens',0)-base_tokens.get('total_tokens',0)} turns +{final_tokens.get('total_turns',0)-base_tokens.get('total_turns',0)}")
print("\n[SCRIPT DONE]")
