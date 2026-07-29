# -*- coding: utf-8 -*-
"""Regression suite after prompt optimization stages.
Tests: QQ casual, QQ terminal task, QQ multi-step install task, web chat.
Measures prompt tokens per scenario."""
import requests, time, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
BRIDGE = "http://127.0.0.1:33333"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermMan\dev\TermMan\de_bug\_mock_qq.log"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def tokens(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()

def workflows(h):
    return requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10).json().get("workflows", [])

def replies_since(n0):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return [l.strip() for l in f.readlines()[n0:] if "QQ [" in l]

def log_len():
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return len(f.readlines())

_mid = int(time.time()) % 10000 * 100
def send_qq(text):
    global _mid
    _mid += 1
    evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
           "message_type": "private", "sub_type": "friend", "message_id": _mid,
           "user_id": 2537134688,
           "message": [{"type": "text", "data": {"text": text}}],
           "raw_message": text, "font": 0,
           "sender": {"user_id": 2537134688, "nickname": "FLY"}}
    r = requests.post(f"{BRIDGE}/onebot/v11/", json=evt, headers={"X-Self-ID": "10001"}, timeout=15)
    return r.status_code

def wait_reply(mark, timeout=90, extra=0):
    t0 = time.time()
    want = len(replies_since(mark)) + 1 + extra
    base = len(replies_since(mark))
    while time.time() - t0 < timeout:
        if len(replies_since(mark)) >= base + 1:
            time.sleep(2)
            return replies_since(mark)[base:]
        time.sleep(3)
    return replies_since(mark)[base:]

def running_jobs(h):
    try:
        d = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10).json()
        return [j for j in d.get("jobs", []) if j.get("status") == "running"]
    except Exception:
        return []

def wait_task_done(h, mark, timeout=600):
    """Plan-mode compatible: settle when no active workflow, no running jobs,
    and at least one QQ reply has arrived since mark."""
    t0 = time.time()
    idle = 0
    while time.time() - t0 < timeout:
        wf = workflows(h)
        active = [w for w in wf if w.get("status") in ("active","running","pending","waiting_job","verifying","blocked","ready_to_report","reporting")]
        busy = bool(active) or bool(running_jobs(h))
        has_reply = len(replies_since(mark)) > 0
        if not busy and has_reply:
            idle += 1
            if idle >= 2:
                return True
        else:
            idle = 0
        time.sleep(10)
    return False

h = login()
results = {}

# ---- T1: QQ casual ----
print("[T1] QQ casual: 10+10等于几", flush=True)
mark = log_len()
tk0 = tokens(h)
send_qq("10+10等于几")
reps = wait_reply(mark, 90)
tk1 = tokens(h)
ok = any("20" in r for r in reps)
results["T1_casual"] = ok
print(f"  replies={len(reps)} ok={ok} prompt_tokens={tk1['total_prompt_tokens']-tk0['total_prompt_tokens']} turns={tk1['total_turns']-tk0['total_turns']}")
for r in reps:
    print(f"    {r[:130]}")

# ---- T2: QQ terminal task ----
print("\n[T2] QQ task: 跑一下 uptime", flush=True)
mark = log_len()
tk0 = tokens(h)
send_qq("跑一下 uptime 看看负载")
reps = wait_reply(mark, 120)
tk1 = tokens(h)
ok = len(reps) > 0 and any(("负载" in r or "load" in r.lower() or "运行" in r) for r in reps)
results["T2_task"] = ok
print(f"  replies={len(reps)} ok={ok} prompt_tokens={tk1['total_prompt_tokens']-tk0['total_prompt_tokens']} turns={tk1['total_turns']-tk0['total_turns']}")
for r in reps:
    print(f"    {r[:130]}")

# ---- T3: QQ multi-step install task ----
print("\n[T3] QQ multi-step: install cmatrix + verify", flush=True)
mark = log_len()
tk0 = tokens(h)
send_qq("帮我安装 cmatrix，装完验证一下装好了")
settled = wait_task_done(h, mark, 600)
time.sleep(5)
reps = replies_since(mark)
tk1 = tokens(h)
import subprocess
ver = subprocess.run(["docker", "exec", "termman-daemon-1", "bash", "-c", "which cmatrix"],
                     capture_output=True, timeout=15)
installed = ver.returncode == 0
results["T3_install"] = installed and len(reps) > 0
print(f"  wf_settled={settled} cmatrix_installed={installed} replies={len(reps)} prompt_tokens={tk1['total_prompt_tokens']-tk0['total_prompt_tokens']} turns={tk1['total_turns']-tk0['total_turns']}")
for r in reps:
    print(f"    {r[:150]}")

# ---- T4: web chat ----
print("\n[T4] web chat", flush=True)
tk0 = tokens(h)
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
                  json={"message": "你好，简单介绍一下你自己", "history": []},
                  headers=h, timeout=120)
tk1 = tokens(h)
ok = r.status_code == 200
results["T4_web"] = ok
content = ""
try:
    content = r.json().get("content", "")[:120]
except Exception:
    content = r.text[:120]
print(f"  status={r.status_code} ok={ok} prompt_tokens={tk1['total_prompt_tokens']-tk0['total_prompt_tokens']}")
print(f"    reply: {content}")

# ---- summary ----
print("\n" + "=" * 60)
print("[REGRESSION SUMMARY]")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("=" * 60)
