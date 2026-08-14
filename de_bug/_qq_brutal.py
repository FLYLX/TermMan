# -*- coding: utf-8 -*-
"""Brutal QQ stress test: ~55 mixed messages at 1-2s cadence.
Covers: rapid math, terminal commands, background-job task, duplicate
messages (tool-loop guard), multi-sender group messages, long text.
Monitors replies, pending queues, backend errors (encoding-safe)."""
import requests, time, json, sys, io, subprocess, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"
GROUP = 770362397
USER = 2537134688
USER2 = 987654321

MESSAGES = [
    # burst 1: rapid math, 1s apart
    (0, "private", USER, "B#01 111+222=?"),
    (1, "group",   USER, "B#02 333+444=?"),
    (1, "private", USER, "B#03 555*2=?"),
    (1, "group",   USER2, "B#04 我是另一个人，6*7=?"),
    (1, "private", USER, "B#05 100-58=?"),
    (1, "group",   USER, "B#06 81/9=?"),
    (1, "private", USER, "B#07 12*12=?"),
    (1, "group",   USER2, "B#08 我也是问问题：13*13=?"),
    # burst 2: terminal commands
    (2, "private", USER, "B#09 跑一下 uptime"),
    (2, "group",   USER, "B#10 看看内存 free -h"),
    (2, "private", USER, "B#11 ls /tmp 有啥"),
    (2, "group",   USER, "B#12 磁盘 df -h /"),
    # burst 3: background job
    (2, "private", USER, "B#13 后台跑 sleep 25 && echo bg-done-13，完事告诉我"),
    (3, "group",   USER, "B#14 后台跑 sleep 30 && echo bg-done-14，好了说一声"),
    # burst 4: duplicates (tool-loop guard territory)
    (2, "private", USER, "B#15 跑一下 uptime"),
    (1, "private", USER, "B#16 跑一下 uptime"),
    (1, "private", USER, "B#17 跑一下 uptime"),
    # burst 5: mixed chatter while jobs run
    (2, "group",   USER, "B#18 现在忙不忙呀"),
    (1, "private", USER, "B#19 你还在吗"),
    (1, "group",   USER2, "B#20 机器人还活着吗"),
    (1, "private", USER, "B#21 1+1=?"),
    (1, "group",   USER, "B#22 2+2=?"),
    (1, "private", USER, "B#23 3+3=?"),
    (1, "group",   USER2, "B#24 4+4=?"),
    (1, "private", USER, "B#25 5+5=?"),
    (1, "group",   USER, "B#26 6+6=?"),
    # burst 6: long message
    (1, "private", USER, "B#27 " + "很长的话" * 60),
    # burst 7: more rapid fire
    (2, "group",   USER, "B#28 7*7=?"),
    (1, "private", USER, "B#29 8*8=?"),
    (1, "group",   USER2, "B#30 9*9=?"),
    (1, "private", USER, "B#31 10*10=?"),
    (1, "group",   USER, "B#32 11*11=?"),
    (1, "private", USER, "B#33 12*11=?"),
    (1, "group",   USER2, "B#34 我是谁"),
    (1, "private", USER, "B#35 今天天气怎么样"),
    (1, "group",   USER, "B#36 14*3=?"),
    (1, "private", USER, "B#37 15*4=?"),
    # burst 8: wait for bg jobs then ask about them
    (20, "private", USER, "B#38 我那个 sleep 后台任务好了没"),
    (2, "group",   USER, "B#39 后台任务完成了吗"),
    # burst 9: final rapid burst
    (3, "private", USER, "B#40 16*2=?"),
    (1, "group",   USER, "B#41 17*2=?"),
    (1, "private", USER, "B#42 18*2=?"),
    (1, "group",   USER2, "B#43 19*2=?"),
    (1, "private", USER, "B#44 20*2=?"),
    (1, "group",   USER, "B#45 21*2=?"),
    (1, "private", USER, "B#46 22*2=?"),
    (1, "group",   USER2, "B#47 23*2=?"),
    (1, "private", USER, "B#48 24*2=?"),
    (1, "group",   USER, "B#49 25*2=?"),
    (1, "private", USER, "B#50 26*2=?"),
]

_msg_id = int(time.time()) % 10000 * 100
def send_event(conv, user, text):
    global _msg_id
    _msg_id += 1
    if conv == "group":
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "group", "sub_type": "normal", "message_id": _msg_id,
               "group_id": GROUP, "user_id": user,
               "message": [{"type": "at", "data": {"qq": "10001"}},
                            {"type": "text", "data": {"text": f" {text}"}}],
               "raw_message": f"[CQ:at,qq=10001] {text}", "font": 0,
               "sender": {"user_id": user, "nickname": f"U{user}"}, "anonymous": None}
    else:
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "private", "sub_type": "friend", "message_id": _msg_id,
               "user_id": user,
               "message": [{"type": "text", "data": {"text": text}}],
               "raw_message": text, "font": 0,
               "sender": {"user_id": user, "nickname": f"U{user}"}}
    try:
        r = requests.post(f"{BRIDGE}/onebot/v11/", json=evt,
                          headers={"X-Self-ID": "10001"}, timeout=15)
        return r.status_code
    except Exception as e:
        return str(e)

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def pending_snapshot(h):
    try:
        d = requests.get(f"{BASE}/api/v1/robots/items/{ITEM}/conversation-controllers",
                         headers=h, timeout=10).json()
        return {cc.get("conversation_key"): (cc.get("status"), cc.get("processing"), cc.get("pending_count"))
                for robot in d.get("robots", []) for cc in robot.get("conversation_controllers", [])}
    except Exception as e:
        return {"error": str(e)}

def backend_errors_since(seconds, seen):
    try:
        p = subprocess.run(["docker", "logs", "TermPaws-backend-1", "--since", f"{seconds}s"],
                           capture_output=True, timeout=30)
        out = p.stdout.decode("utf-8", errors="replace") + p.stderr.decode("utf-8", errors="replace")
        new = []
        for line in out.splitlines():
            if any(k in line for k in ("ERROR", "BadRequest", "Traceback", "Exception", "queue may stall")):
                key = line.strip()[:150]
                if key not in seen:
                    seen.add(key)
                    new.append(key)
        return new
    except Exception:
        return []

print("=" * 60)
print(f"BRUTAL QQ STRESS: {len(MESSAGES)} messages, ~1s cadence")
print("=" * 60)

with open(LOG, encoding="utf-8", errors="replace") as f:
    log0 = len(f.readlines())
h = login()
pend0 = pending_snapshot(h)
print(f"pre-test pending: {pend0}")

t0 = time.time()
sent = []
err_seen = set()

def sender_thread():
    for delay, conv, user, text in MESSAGES:
        time.sleep(delay)
        tag = text.split()[0]
        st = send_event(conv, user, text)
        sent.append(tag)
        print(f"[{int(time.time()-t0):4d}s] >>> {conv}/{user} '{text[:30]}' -> {st}", flush=True)

st = threading.Thread(target=sender_thread, daemon=True)
st.start()

while st.is_alive():
    time.sleep(15)
    el = int(time.time() - t0)
    with open(LOG, encoding="utf-8", errors="replace") as f:
        replies = sum(1 for l in f.readlines()[log0:] if "QQ [" in l)
    for e in backend_errors_since(20, err_seen):
        print(f"  [{el}s] [BACKEND-ERR] {e[:170]}", flush=True)
    print(f"  [{el:4d}s] sent={len(sent)} replies={replies} pending={pending_snapshot(h)}", flush=True)

print("\n[GRACE] waiting 150s for stragglers + bg jobs...")
for i in range(10):
    time.sleep(15)
    el = int(time.time() - t0)
    with open(LOG, encoding="utf-8", errors="replace") as f:
        replies = sum(1 for l in f.readlines()[log0:] if "QQ [" in l)
    pend = pending_snapshot(h)
    for e in backend_errors_since(20, err_seen):
        print(f"  [{el}s] [BACKEND-ERR] {e[:170]}", flush=True)
    print(f"  [{el:4d}s] replies={replies} pending={pend}", flush=True)
    if all(v[2] == 0 for v in pend.values() if isinstance(v, tuple)) and i >= 6:
        break

print("\n" + "=" * 60)
print("[REPORT]")
print("=" * 60)
with open(LOG, encoding="utf-8", errors="replace") as f:
    new_lines = f.readlines()[log0:]
reply_lines = [l.strip() for l in new_lines if "QQ [" in l]
print(f"sent={len(sent)} reply_bubbles={len(reply_lines)}")
for l in reply_lines:
    print(f"  {l[:160]}")
print(f"\nfinal pending: {pending_snapshot(h)}")
print(f"backend errors: {len(err_seen)}")
for e in list(err_seen)[:15]:
    print(f"  {e[:170]}")
print(f"total elapsed: {int(time.time()-t0)}s")
print("\n[SCRIPT DONE]")
