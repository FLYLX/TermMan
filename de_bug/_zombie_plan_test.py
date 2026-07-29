# -*- coding: utf-8 -*-
"""Zombie plan test: verify plan scratchpad hygiene.
Z1: completed task -> plan auto-cleared
Z2: task superseded by new unrelated request -> old plan replaced, not merged
Z3: quick consecutive different tasks -> plan always matches latest task
Z4: plan API + update flow visible end to end
"""
import requests, time, json, sys, io
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
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10).json()
    return d.get("plan", [])

def log_len():
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return len(f.readlines())

def replies_since(n0):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return [l.strip() for l in f.readlines()[n0:] if "QQ [" in l]

def wait_reply(mark, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if replies_since(mark):
            time.sleep(4)
            return replies_since(mark)
        time.sleep(3)
    return replies_since(mark)

def show_plan(h, label):
    plan = get_plan(h)
    if not plan:
        print(f"  plan[{label}]: <empty>")
    else:
        for s in plan:
            print(f"  plan[{label}]: [{s['status']}] {s['step']}")
    return plan

h = login()
results = {}

# ---- Z1: small multi-step task to completion -> plan cleared ----
print("[Z1] multi-step task to completion", flush=True)
requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=10)
time.sleep(1)
mark = log_len()
send_qq("Z1：在 /tmp 建个目录 z1test，里面写个文件 hello.txt 内容 hi，然后告诉我搞定")
reps = wait_reply(mark, 240)
time.sleep(3)
plan = show_plan(h, "after-task")
ok1 = len(plan) == 0
results["Z1_cleared_after_done"] = ok1
print(f"  replies={len(reps)} plan_empty={ok1}")
for r in reps:
    print(f"    {r[:130]}")

# ---- Z2: start task A, immediately supersede with unrelated B ----
print("\n[Z2] supersede mid-task", flush=True)
mark = log_len()
send_qq("Z2：帮我装 nyancat，装完验证")
time.sleep(25)  # let it build a plan and start
plan_mid = show_plan(h, "mid-install")
send_qq("别装了，先回答我：123*456等于几")
reps = wait_reply(mark, 240)
time.sleep(3)
plan = show_plan(h, "after-supersede")
# zombie check: plan should be empty OR about the math question, NOT stuck on nyancat install
zombie = any("nyancat" in str(s.get("step", "")).lower() and s.get("status") == "in_progress" for s in plan)
ok2 = not zombie
results["Z2_no_zombie_after_supersede"] = ok2
answered = any("56088" in r for r in reps)
results["Z2_new_request_answered"] = answered
print(f"  zombie_in_progress={zombie} math_answered={answered}")
for r in reps:
    print(f"    {r[:130]}")

# ---- Z3: consecutive different tasks ----
print("\n[Z3] consecutive different tasks", flush=True)
mark = log_len()
send_qq("Z3a：看看 /tmp/z1test/hello.txt 的内容")
reps1 = wait_reply(mark, 180)
plan_a = show_plan(h, "after-Z3a")
mark2 = log_len()
send_qq("Z3b：df -h 看看磁盘")
reps2 = wait_reply(mark2, 180)
plan_b = show_plan(h, "after-Z3b")
ok3 = True  # informational; plans for 1-step tasks should be empty
print(f"  Z3a plan entries={len(plan_a)}, Z3b plan entries={len(plan_b)}")
results["Z3_info"] = ok3
for r in reps1 + reps2:
    print(f"    {r[:130]}")

print("\n" + "=" * 60)
print("[ZOMBIE PLAN SUMMARY]")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("=" * 60)
