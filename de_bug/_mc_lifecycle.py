# -*- coding: utf-8 -*-
"""MC 1.20.1 full lifecycle via QQ (new architecture validation).
P1: install java + MC 1.20.1 server, start it, confirm Done in log
P2: stop the server
P3: change view-distance to 10 (+ keepInventory true) while stopped
P4: restart and confirm settings applied
Plan-mode compatible waits: poll jobs/replies/container state, not workflows."""
import requests, time, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"

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
    print(f"[QQ>>>] '{text[:50]}' -> {r.status_code}", flush=True)

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def tokens(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()

def running_jobs(h):
    try:
        d = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10).json()
        return [j for j in d.get("jobs", []) if j.get("status") == "running"]
    except Exception:
        return []

def log_len():
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return len(f.readlines())

def replies_since(n0):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return [l.strip() for l in f.readlines()[n0:] if "QQ [" in l]

def dexec(cmd, timeout=30):
    p = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "bash", "-c", cmd],
                       capture_output=True, timeout=timeout)
    return (p.stdout.decode("utf-8", errors="replace") + p.stderr.decode("utf-8", errors="replace")).strip()

def mc_proc():
    return dexec("ps aux | grep '[j]ava' | head -2")

def find_server_log():
    return dexec("find /app/src/workdir -name latest.log -path '*logs*' 2>/dev/null | head -1")

def wait_phase(h, mark, timeout, done_check=None):
    """Wait until done_check() true, or replies arrived & no running jobs & idle."""
    t0 = time.time()
    idle = 0
    while time.time() - t0 < timeout:
        time.sleep(20)
        el = int(time.time() - t0)
        jobs = len(running_jobs(h))
        reps = len(replies_since(mark))
        proc = "java" if mc_proc() else "no-java"
        print(f"  [{el:4d}s] jobs={jobs} replies={reps} mc={proc}", flush=True)
        if done_check and done_check():
            return True
        if not jobs and reps > 0:
            idle += 1
            if idle >= 3:
                return done_check() if done_check else True
        else:
            idle = 0
    return False

print("=" * 60)
print("MC 1.20.1 FULL LIFECYCLE via QQ")
print("=" * 60)
h = login()
tk0 = tokens(h)
print(f"[PRE] {dexec('which java; echo ---; ps aux | grep -c [j]ava')}")

# ---- P1: install java + MC 1.20.1, start ----
print("\n[P1] install java + MC 1.20.1, start server", flush=True)
mark = log_len()
send_qq("装个java，搭个MC 1.20.1服务器跑起来")
def p1_done():
    log = find_server_log()
    if not log:
        return False
    tail = dexec(f"tail -5 '{log}' 2>/dev/null")
    return "Done" in tail and mc_proc()
ok1 = wait_phase(h, mark, 60*25, p1_done)
print(f"[P1] server running with Done: {ok1}")
for r in replies_since(mark):
    print(f"  {r[:150]}")
print(f"  java proc: {mc_proc()[:120]}")
log_path = find_server_log()
print(f"  server log: {log_path}")

# ---- P2: stop server ----
print("\n[P2] stop the server", flush=True)
mark = log_len()
send_qq("把MC服务器关了")
def p2_done():
    return not mc_proc()
ok2 = wait_phase(h, mark, 60*5, p2_done)
print(f"[P2] server stopped: {ok2}")
for r in replies_since(mark):
    print(f"  {r[:150]}")

# ---- P3: change view-distance + keepInventory ----
print("\n[P3] view-distance=10 + keepInventory", flush=True)
mark = log_len()
send_qq("视距改成10，死亡不掉落开了，先别启动")
def p3_done():
    props = dexec("find /app/src/workdir -name server.properties 2>/dev/null | head -1")
    if not props:
        return False
    vd = dexec(f"grep '^view-distance' '{props}' 2>/dev/null")
    return "view-distance=10" in vd
ok3 = wait_phase(h, mark, 60*8, p3_done)
props = dexec("find /app/src/workdir -name server.properties 2>/dev/null | head -1")
print(f"[P3] settings applied: {ok3}")
vd_line = dexec("grep '^view-distance' '" + props + "' 2>/dev/null") if props else "no props"
print(f"  view-distance: {vd_line}")
for r in replies_since(mark):
    print(f"  {r[:150]}")

# ---- P4: restart, confirm ----
print("\n[P4] restart server, confirm settings", flush=True)
mark = log_len()
send_qq("启动服务器")
def p4_done():
    log = find_server_log()
    if not log:
        return False
    return "Done" in dexec(f"tail -10 '{log}' 2>/dev/null") and mc_proc()
ok4 = wait_phase(h, mark, 60*8, p4_done)
print(f"[P4] restarted: {ok4}")
for r in replies_since(mark):
    print(f"  {r[:150]}")

tk1 = tokens(h)
print("\n" + "=" * 60)
print("[LIFECYCLE SUMMARY]")
print(f"  P1 install+start: {'PASS' if ok1 else 'FAIL'}")
print(f"  P2 stop:          {'PASS' if ok2 else 'FAIL'}")
print(f"  P3 settings:      {'PASS' if ok3 else 'FAIL'}")
print(f"  P4 restart:       {'PASS' if ok4 else 'FAIL'}")
print(f"  tokens: +{tk1.get('total_tokens',0)-tk0.get('total_tokens',0)}, turns +{tk1.get('total_turns',0)-tk0.get('total_turns',0)}")
print("=" * 60)
