# -*- coding: utf-8 -*-
"""Interrupt/winding task test via QQ path.
P1: install java17 (long task starts)
P2: +30s "先别装了" (interrupt)
P3: +20s "继续装吧" (resume)
P4: +45s "别装17了装21吧" (change target mid-task)
P5: settle -> java installed? report? plan cleared? no stuck pending?
"""
import requests, time, subprocess, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
BRIDGE = "http://127.0.0.1:33333"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermMan\dev\TermMan\de_bug\_mock_qq.log"

_mid = int(time.time()) % 10000 * 100
def send(text):
    global _mid
    _mid += 1
    evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
           "message_type": "private", "sub_type": "friend", "message_id": _mid,
           "user_id": 2537134688,
           "message": [{"type": "text", "data": {"text": text}}],
           "raw_message": text, "font": 0,
           "sender": {"user_id": 2537134688, "nickname": "FLY"}}
    r = requests.post(f"{BRIDGE}/onebot/v11/", json=evt, headers={"X-Self-ID": "10001"}, timeout=15)
    print(f"[QQ>>>] '{text}' -> {r.status_code}", flush=True)

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def plan(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10).json().get("plan", [])

def pending(h):
    try:
        d = requests.get(f"{BASE}/api/v1/robots/items/{ITEM}/conversation-controllers", headers=h, timeout=10).json()
        return {cc.get("conversation_key"): cc.get("pending_count")
                for robot in d.get("robots", []) for cc in robot.get("conversation_controllers", [])}
    except Exception:
        return {}

def jobs(h):
    try:
        d = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10).json()
        return [j.get("command", "")[:40] for j in d.get("jobs", []) if j.get("status") == "running"]
    except Exception:
        return []

def java_version():
    p = subprocess.run(["docker", "exec", "termman-daemon-1", "bash", "-c", "java -version 2>&1 | head -1"],
                       capture_output=True, timeout=15)
    return (p.stdout.decode() + p.stderr.decode()).strip()

h = login()
requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h, timeout=30)
time.sleep(2)
mark = len(open(LOG, encoding="utf-8", errors="replace").readlines())
log = []

def snap(label):
    p = plan(h)
    j = jobs(h)
    pend = pending(h)
    line = f"  [{label}] plan={[(s['step'][:14], s['status'][:4]) for s in p]} jobs={j} pending={pend}"
    print(line, flush=True)
    log.append(line)

print("=== P1: install java17 ===", flush=True)
send("装个java17，装完验证一下告诉我")
time.sleep(30)
snap("P1+30s")

print("=== P2: interrupt ===", flush=True)
send("先别装了，停一下")
time.sleep(20)
snap("P2+20s")

print("=== P3: resume ===", flush=True)
send("继续装吧")
time.sleep(45)
snap("P3+45s")

print("=== P4: change target ===", flush=True)
send("别装17了，装21吧")
time.sleep(30)
snap("P4+30s")

print("=== P5: settle (up to 12min) ===", flush=True)
t0 = time.time()
final_java = ""
while time.time() - t0 < 720:
    time.sleep(30)
    el = int(time.time() - t0)
    p = plan(h)
    j = jobs(h)
    reps = [l.strip() for l in open(LOG, encoding="utf-8", errors="replace").readlines()[mark:] if "QQ [" in l]
    v = java_version()
    print(f"  [{el}s] plan={len(p)} jobs={len(j)} replies={len(reps)} java={v[:45]}", flush=True)
    if "openjdk" in v and not j:
        final_java = v
        time.sleep(15)
        break

snap("final")
print("\n=== QQ replies ===")
for l in [l.strip() for l in open(LOG, encoding="utf-8", errors="replace").readlines()[mark:] if "QQ [" in l]:
    print(f"  {l[:150]}")
print("\nfinal java:", java_version()[:80])
print("final plan:", plan(h))
print("final pending:", pending(h))
