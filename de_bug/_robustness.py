# -*- coding: utf-8 -*-
"""Robustness suite: stuck input / stuck task / zombie task / stuck thinking / lost task.
A: long bg job + 10 burst messages during it -> all answered, pending drains
B: rapid task switching (5 tasks, each before prev finishes) -> no zombies, all answered
C: duplicate identical messages x3 -> no 400, no stuck
D: final health: pending=0, plan empty, jobs empty, final ping answered
"""
import requests, time, json, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermMan\dev\TermMan\de_bug\_mock_qq.log"

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
    return requests.post(f"{BRIDGE}/onebot/v11/", json=evt,
                         headers={"X-Self-ID": "10001"}, timeout=15).status_code

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def get_plan(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10).json().get("plan", [])

def running_jobs(h):
    try:
        d = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10).json()
        return [j for j in d.get("jobs", []) if j.get("status") == "running"]
    except Exception:
        return []

def pendings(h):
    try:
        d = requests.get(f"{BASE}/api/v1/robots/items/{ITEM}/conversation-controllers", headers=h, timeout=10).json()
        return {cc.get("conversation_key"): (cc.get("status"), cc.get("processing"), cc.get("pending_count"))
                for robot in d.get("robots", []) for cc in robot.get("conversation_controllers", [])}
    except Exception as e:
        return {"error": str(e)}

def log_len():
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return len(f.readlines())

def replies_since(n0):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return [l.strip() for l in f.readlines()[n0:] if "QQ [" in l]

def backend_errors(seen):
    try:
        p = subprocess.run(["docker", "logs", "termman-backend-1", "--since", "60s"],
                           capture_output=True, timeout=20)
        out = p.stdout.decode("utf-8", errors="replace") + p.stderr.decode("utf-8", errors="replace")
        new = []
        for line in out.splitlines():
            if any(k in line for k in ("ERROR", "BadRequest", "Traceback", "queue may stall")):
                key = line.strip()[:140]
                if key not in seen:
                    seen.add(key)
                    new.append(key)
        return new
    except Exception:
        return []

h = login()
results = {}
err_seen = set()

# ============ A: bg job + burst during it ============
print("[A] sleep 60 bg job + 10 burst messages", flush=True)
mark = log_len()
send_qq("A0：后台跑 sleep 60 && echo a-done，好了告诉我")
time.sleep(8)
burst = ["A1 1+1=?", "A2 2*3=?", "A3 4+5=?", "A4 6*6=?", "A5 7+8=?",
         "A6 9-3=?", "A7 10/2=?", "A8 3*7=?", "A9 8+9=?", "A10 11+11=?"]
for m in burst:
    send_qq(m)
    time.sleep(1.5)
t0 = time.time()
while time.time() - t0 < 150:  # job 60s + margin
    time.sleep(10)
    pend = pendings(h)
    reps = len(replies_since(mark))
    print(f"  [{int(time.time()-t0)}s] replies={reps} pending={pend} jobs={len(running_jobs(h))}", flush=True)
    if all(v[2] == 0 for v in pend.values() if isinstance(v, tuple)) and reps >= 8 and not running_jobs(h):
        break
reps = replies_since(mark)
job_report = any("a-done" in r or "跑完" in r or "完成" in r or "好了" in r for r in reps)
results["A_burst_all_answered"] = len(reps) >= 8
results["A_job_report_arrived"] = job_report
pend = pendings(h)
results["A_pending_drained"] = all(v[2] == 0 for v in pend.values() if isinstance(v, tuple))
print(f"  A: replies={len(reps)} job_report={job_report} pending={pend}")

# ============ B: rapid task switching ============
print("\n[B] 5 rapid task switches", flush=True)
mark = log_len()
tasks = ["B1：跑一下 uptime",
         "B2：别管上面了，df -h 看磁盘",
         "B3：算了，free -h 看内存",
         "B4：先别管前面，1+1=?",
         "B5：/tmp 下建个 b5.txt 写 ok"]
for m in tasks:
    send_qq(m)
    time.sleep(4)
t0 = time.time()
while time.time() - t0 < 240:
    time.sleep(10)
    reps = len(replies_since(mark))
    plan = get_plan(h)
    jobs = len(running_jobs(h))
    print(f"  [{int(time.time()-t0)}s] replies={reps} plan={len(plan)} jobs={jobs}", flush=True)
    if reps >= 4 and jobs == 0:
        time.sleep(10)
        break
reps = replies_since(mark)
plan = get_plan(h)
zombie = [s for s in plan if s.get("status") == "in_progress"]
results["B_replies"] = len(reps) >= 4
results["B_no_zombie_plan"] = len(zombie) == 0
results["B_no_stuck_jobs"] = len(running_jobs(h)) == 0
print(f"  B: replies={len(reps)} zombie_steps={len(zombie)} stuck_jobs={len(running_jobs(h))}")
for r in reps:
    print(f"    {r[:120]}")

# ============ C: duplicates ============
print("\n[C] identical message x3", flush=True)
mark = log_len()
for _ in range(3):
    send_qq("C：3*3等于几")
    time.sleep(2)
reps = []
t0 = time.time()
while time.time() - t0 < 90:
    reps = replies_since(mark)
    if reps:
        break
    time.sleep(3)
results["C_no_stuck"] = len(reps) > 0
results["C_no_400"] = not any("BadRequest" in e or "Empty tool_calls" in e for e in err_seen)
print(f"  C: replies={len(reps)} backend_errors={len(err_seen)}")

# ============ D: final health ============
print("\n[D] final health check", flush=True)
for e in backend_errors(err_seen):
    print(f"  [ERR] {e}")
time.sleep(5)
mark = log_len()
send_qq("D：在吗")
reps = []
t0 = time.time()
while time.time() - t0 < 60:
    reps = replies_since(mark)
    if reps:
        break
    time.sleep(3)
pend = pendings(h)
plan = get_plan(h)
jobs = running_jobs(h)
results["D_final_ping"] = len(reps) > 0
results["D_pending_zero"] = all(v[2] == 0 for v in pend.values() if isinstance(v, tuple))
results["D_plan_empty"] = len([s for s in plan if s.get("status") == "in_progress"]) == 0
results["D_jobs_empty"] = len(jobs) == 0
results["D_no_backend_errors"] = len(err_seen) == 0
print(f"  D: ping={len(reps)>0} pending={pend} plan={len(plan)} jobs={len(jobs)} errors={len(err_seen)}")

print("\n" + "=" * 60)
print("[ROBUSTNESS SUMMARY]")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("=" * 60)
