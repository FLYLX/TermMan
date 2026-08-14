# -*- coding: utf-8 -*-
"""Full-channel dialogue + broadcast delivery suite.
T1: QQ private casual multi-turn (4 exchanges, no stuck)
T2: QQ group casual (2 exchanges)
T3: web casual dialogue (2 messages)
T4: web task + broadcast result to QQ group ("做完事广播")
T5: QQ group task + report in same group
T6: web broadcast to both private and group (explicit multi-target)
T7: final stuck check: pending=0, plan empty, jobs empty, ping works
"""
import requests, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"
GROUP = 770362397
USER = 2537134688

_mid = int(time.time()) % 10000 * 100
def send_qq(text, group=False):
    global _mid
    _mid += 1
    if group:
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "group", "sub_type": "normal", "message_id": _mid,
               "group_id": GROUP, "user_id": USER,
               "message": [{"type": "at", "data": {"qq": "10001"}},
                            {"type": "text", "data": {"text": f" {text}"}}],
               "raw_message": f"[CQ:at,qq=10001] {text}", "font": 0,
               "sender": {"user_id": USER, "nickname": "FLY"}, "anonymous": None}
    else:
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "private", "sub_type": "friend", "message_id": _mid,
               "user_id": USER, "message": [{"type": "text", "data": {"text": text}}],
               "raw_message": text, "font": 0,
               "sender": {"user_id": USER, "nickname": "FLY"}}
    return requests.post(f"{BRIDGE}/onebot/v11/", json=evt,
                         headers={"X-Self-ID": "10001"}, timeout=15).status_code

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def web_chat(h, msg, timeout=120):
    r = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []},
                      headers=h, timeout=timeout)
    try:
        return r.status_code, r.json().get("content", "")
    except Exception:
        return r.status_code, r.text[:200]

def log_len():
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return len(f.readlines())

def reps_since(mark, substr="", target=""):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        lines = [l.strip() for l in f.readlines()[mark:] if "QQ [" in l]
    if substr:
        lines = [l for l in lines if substr in l]
    if target:
        lines = [l for l in lines if target in l]
    return lines

def wait_for(mark, substr="", target="", timeout=90, at_least=1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        reps = reps_since(mark, substr, target)
        if len(reps) >= at_least:
            return reps
        time.sleep(3)
    return reps_since(mark, substr, target)

def pendings(h):
    try:
        d = requests.get(f"{BASE}/api/v1/robots/items/{ITEM}/conversation-controllers", headers=h, timeout=10).json()
        return {cc.get("conversation_key"): cc.get("pending_count")
                for robot in d.get("robots", []) for cc in robot.get("conversation_controllers", [])}
    except Exception as e:
        return {"error": str(e)}

def get_plan(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10).json().get("plan", [])

def running_jobs(h):
    try:
        d = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10).json()
        return [j for j in d.get("jobs", []) if j.get("status") == "running"]
    except Exception:
        return []

h = login()
results = {}

# ---------- T1: QQ private casual multi-turn ----------
print("[T1] QQ 私聊闲聊 x4", flush=True)
exchanges = ["T1-1 你叫什么名字", "T1-2 你刚说你叫啥来着", "T1-3 3*7等于几", "T1-4 那 4*8 呢"]
ok = 0
for msg in exchanges:
    mark = log_len()
    send_qq(msg)
    reps = wait_for(mark, timeout=60)
    got = len(reps) > 0
    ok += got
    print(f"  '{msg[:20]}' -> {'ok' if got else 'TIMEOUT'}", flush=True)
    for r in reps:
        print(f"    {r[:110]}")
results["T1_qq_casual_x4"] = ok == 4

# ---------- T2: QQ group casual ----------
print("\n[T2] QQ 群闲聊 x2", flush=True)
ok = 0
for msg in ["T2-1 群里谁在", "T2-2 2+2=?"]:
    mark = log_len()
    send_qq(msg, group=True)
    reps = wait_for(mark, target=str(GROUP), timeout=60)
    got = len(reps) > 0
    ok += got
    print(f"  '{msg}' -> {'ok' if got else 'TIMEOUT'}", flush=True)
    for r in reps:
        print(f"    {r[:110]}")
results["T2_group_casual_x2"] = ok == 2

# ---------- T3: web casual ----------
print("\n[T3] web 闲聊 x2", flush=True)
ok = 0
for msg in ["T3-1 你好", "T3-2 5*5=?"]:
    st, content = web_chat(h, msg, 90)
    got = st == 200 and content.strip()
    ok += bool(got)
    print(f"  '{msg}' -> {st} {content[:60]}")
results["T3_web_casual_x2"] = ok == 2

# ---------- T4: web task + broadcast result to QQ group ----------
print("\n[T4] web 任务+广播结果到群", flush=True)
mark = log_len()
st, content = web_chat(h, "T4：跑一下 uptime，然后把结果发到 QQ 群 770362397 里", 180)
print(f"  web reply: {st} {content[:100]}")
reps = wait_for(mark, target=str(GROUP), timeout=90)
got = any(("负载" in r or "运行" in r or "uptime" in r.lower() or "小时" in r) for r in reps)
results["T4_web_task_broadcast_group"] = got
print(f"  群广播送达: {got}")
for r in reps:
    print(f"    {r[:130]}")

# ---------- T5: QQ group task + report in same group ----------
print("\n[T5] QQ群任务+同群汇报", flush=True)
mark = log_len()
send_qq("T5：df -h 看看磁盘，群里汇报", group=True)
reps = wait_for(mark, target=str(GROUP), timeout=120)
got = any(("磁盘" in r or "G" in r or "%" in r) for r in reps)
results["T5_group_task_report"] = got
print(f"  群内任务汇报: {got} replies={len(reps)}")
for r in reps:
    print(f"    {r[:130]}")

# ---------- T6: web broadcast to both ----------
print("\n[T6] web 广播到私聊+群", flush=True)
mark = log_len()
st, content = web_chat(h, "T6：把「多点广播测试」这句话分别发到我的 QQ 私聊 2537134688 和 QQ 群 770362397", 180)
print(f"  web reply: {st} {content[:100]}")
time.sleep(15)
reps = reps_since(mark, substr="多点广播测试")
got_priv = any(str(USER) in r for r in reps)
got_grp = any(str(GROUP) in r for r in reps)
results["T6_broadcast_private"] = got_priv
results["T6_broadcast_group"] = got_grp
print(f"  私聊收到: {got_priv} 群收到: {got_grp}")
for r in reps:
    print(f"    {r[:130]}")

# ---------- T7: stuck check ----------
print("\n[T7] 卡死检查", flush=True)
time.sleep(10)
mark = log_len()
send_qq("T7：在吗")
reps = wait_for(mark, timeout=60)
pend = pendings(h)
plan = get_plan(h)
jobs = running_jobs(h)
results["T7_ping"] = len(reps) > 0
results["T7_pending_zero"] = all(v == 0 for v in pend.values() if isinstance(v, int))
results["T7_plan_clean"] = len([s for s in plan if s.get("status") == "in_progress"]) == 0
results["T7_jobs_empty"] = len(jobs) == 0
print(f"  ping={len(reps)>0} pending={pend} plan={len(plan)} jobs={len(jobs)}")

print("\n" + "=" * 60)
print("[FULL-CHANNEL SUMMARY]")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("=" * 60)
