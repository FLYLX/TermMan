# -*- coding: utf-8 -*-
"""MC 1.20.1 server end-to-end test via simulated QQ path (short prompts).
Phase 1: install java17 + MC 1.20.1 server, start it
Phase 2: count 1-10 inside the server console
Phase 3: restart + keepInventory + view-distance
Monitors workflows, captures QQ replies, verifies inside the container."""
import requests, time, json, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"

_msg_id = int(time.time()) % 10000 * 100
def send_qq(text):
    global _msg_id
    _msg_id += 1
    evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
           "message_type": "private", "sub_type": "friend", "message_id": _msg_id,
           "user_id": 2537134688,
           "message": [{"type": "text", "data": {"text": text}}],
           "raw_message": text, "font": 0,
           "sender": {"user_id": 2537134688, "nickname": "FLY"}}
    r = requests.post(f"{BRIDGE}/onebot/v11/", json=evt,
                      headers={"X-Self-ID": "10001"}, timeout=15)
    print(f"[QQ>>>] '{text[:50]}' -> {r.status_code}", flush=True)

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def get_workflows(h):
    return requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10).json()

def get_tokens(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()

def pending_count(h):
    try:
        d = requests.get(f"{BASE}/api/v1/robots/items/{ITEM}/conversation-controllers",
                         headers=h, timeout=10).json()
        return {cc.get("conversation_key"): cc.get("pending_count")
                for robot in d.get("robots", []) for cc in robot.get("conversation_controllers", [])}
    except Exception:
        return {}

def new_replies(n0):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return [l.strip() for l in f.readlines()[n0:] if "QQ [" in l]

def dexec(cmd, timeout=20):
    p = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "bash", "-c", cmd],
                       capture_output=True, timeout=timeout)
    return (p.stdout.decode("utf-8", errors="replace") + p.stderr.decode("utf-8", errors="replace")).strip()

def wait_settled(h, phase_timeout, log_mark):
    """Poll until no active workflow and no processing; return elapsed."""
    t0 = time.time()
    idle_streak = 0
    while time.time() - t0 < phase_timeout:
        time.sleep(15)
        el = int(time.time() - t0)
        wf = get_workflows(h).get("workflows", [])
        active = [w for w in wf if w.get("status") in ("active", "running", "pending", "waiting_job", "verifying", "blocked", "ready_to_report", "reporting")]
        reps = len(new_replies(log_mark))
        stat = []
        for w in wf:
            steps = w.get("steps", [])
            sd = sum(1 for s in steps if s.get("status") in ("completed", "cancelled", "failed"))
            stat.append(f"{w.get('status')}:{sd}/{len(steps)}")
        print(f"  [{el:4d}s] wf={stat} replies={reps} pending={pending_count(h)}", flush=True)
        if not active:
            idle_streak += 1
            if idle_streak >= 2:  # 30s stable idle
                return el
        else:
            idle_streak = 0
    return -1

print("=" * 60)
print("MC 1.20.1 E2E via QQ (short prompts)")
print("=" * 60)

with open(LOG, encoding="utf-8", errors="replace") as f:
    log0 = len(f.readlines())
h = login()
requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=10)
time.sleep(1)
tok0 = get_tokens(h)
print(f"[BASELINE] tokens={tok0.get('total_tokens',0)}")
print(f"[PRE] container: {dexec('java -version 2>&1 | head -1; ls /app/src/workdir 2>/dev/null | head -5')[:150]}")

# ---------- PHASE 1 ----------
print("\n[PHASE 1] install java17 + MC 1.20.1, start server", flush=True)
mark1 = len(open(LOG, encoding='utf-8', errors='replace').readlines())
send_qq("帮我装个java17，再搭一个MC 1.20.1原版服务器跑起来，EULA同意掉")
el = wait_settled(h, 60 * 25, mark1)
print(f"[PHASE 1] settled after {el}s" if el >= 0 else "[PHASE 1] TIMEOUT 25min")
print("[PHASE 1 replies]")
for l in new_replies(mark1):
    print(f"  {l[:170]}")
print("[PHASE 1 container check]")
print("  java:", dexec("java -version 2>&1 | head -1")[:100])
print("  jars:", dexec("find /app -name '*.jar' -newer /etc/hostname 2>/dev/null | head -5")[:200])
print("  mc proc:", dexec("ps aux | grep -c '[j]ava'")[:50])
print("  eula:", dexec("grep -r eula /app/src/workdir/*/eula.txt 2>/dev/null | head -2")[:100])

# ---------- PHASE 2 ----------
print("\n[PHASE 2] count 1-10 in server console", flush=True)
mark2 = len(open(LOG, encoding='utf-8', errors='replace').readlines())
send_qq("进服务器控制台，从1数到10一个一个发出来")
el = wait_settled(h, 60 * 6, mark2)
print(f"[PHASE 2] settled after {el}s" if el >= 0 else "[PHASE 2] TIMEOUT 6min")
print("[PHASE 2 replies]")
for l in new_replies(mark2):
    print(f"  {l[:170]}")
print("[PHASE 2 server log tail]")
print(dexec("tail -25 /app/src/workdir/*/logs/latest.log 2>/dev/null | grep -iE 'say|[1-9]|10' | tail -15")[:600])

# ---------- PHASE 3 ----------
print("\n[PHASE 3] restart + keepInventory + view-distance", flush=True)
mark3 = len(open(LOG, encoding='utf-8', errors='replace').readlines())
send_qq("重启一下服务器，把死亡不掉落开了，视距改成10")
el = wait_settled(h, 60 * 10, mark3)
print(f"[PHASE 3] settled after {el}s" if el >= 0 else "[PHASE 3] TIMEOUT 10min")
print("[PHASE 3 replies]")
for l in new_replies(mark3):
    print(f"  {l[:170]}")
print("[PHASE 3 verify]")
print("  view-distance:", dexec("grep view-distance /app/src/workdir/*/server.properties 2>/dev/null")[:100])
print("  keepInventory:", dexec("tail -40 /app/src/workdir/*/logs/latest.log 2>/dev/null | grep -i keepInventory | tail -3")[:200])
print("  mc proc:", dexec("ps aux | grep -c '[j]ava'")[:50])
print("  uptime:", dexec("tail -5 /app/src/workdir/*/logs/latest.log 2>/dev/null | tail -3")[:300])

tok1 = get_tokens(h)
print(f"\n[TOKENS] +{tok1.get('total_tokens',0)-tok0.get('total_tokens',0)} total, "
      f"prompt +{tok1.get('total_prompt_tokens',0)-tok0.get('total_prompt_tokens',0)}, "
      f"completion +{tok1.get('total_completion_tokens',0)-tok0.get('total_completion_tokens',0)}, "
      f"turns +{tok1.get('total_turns',0)-tok0.get('total_turns',0)}")
print("\n[SCRIPT DONE]")
