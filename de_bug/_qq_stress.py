# -*- coding: utf-8 -*-
"""QQ path stress test: rapid mixed private/group NapCat events.
Tracks per-message reply latency via mock_napcat log, pending queue depth,
and backend errors. Prints a timeline; anomalies are flagged."""
import requests, time, json, sys, io, subprocess, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"
GROUP = 770362397
USER = 2537134688

MESSAGES = [
    # (delay_before_send_sec, conv, text, expect_reply_substr)
    (0,  "private", "stress#01 2+2等于几", "4"),
    (3,  "group",   "stress#02 3+3等于几", "6"),
    (3,  "private", "stress#03 现在服务器负载多少", None),
    (4,  "group",   "stress#04 讲个一句话笑话", None),
    (4,  "private", "stress#05 5*5等于几", "25"),
    (3,  "group",   "stress#06 7*8等于几", "56"),
    (5,  "private", "stress#07 跑一下 uptime 看看", None),
    (8,  "group",   "stress#08 9*9等于几", "81"),
    (4,  "private", "stress#09 你是谁", None),
    (4,  "group",   "stress#10 11+11等于几", "22"),
    (6,  "private", "stress#11 12*12等于几", "144"),
    (3,  "group",   "stress#12 现在几个人在线", None),
    (8,  "private", "stress#13 13+13等于几", "26"),
    (3,  "group",   "stress#14 14*2等于几", "28"),
    (5,  "private", "stress#15 df -h 看一下磁盘", None),
    (10, "group",   "stress#16 15*15等于几", "225"),
    (3,  "private", "stress#17 16+4等于几", "20"),
    (3,  "group",   "stress#17b 跟一句：17+17呢", "34"),
    (6,  "private", "stress#18 18*2等于几", "36"),
    (3,  "group",   "stress#19 19+1等于几", "20"),
    (5,  "private", "stress#20 20*20等于几", "400"),
]

_msg_id = int(time.time()) % 10000 * 100
def send_event(conv, text):
    global _msg_id
    _msg_id += 1
    if conv == "group":
        raw = f"[CQ:at,qq=10001] {text}"
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "group", "sub_type": "normal", "message_id": _msg_id,
               "group_id": GROUP, "user_id": USER,
               "message": [{"type": "at", "data": {"qq": "10001"}},
                            {"type": "text", "data": {"text": f" {text}"}}],
               "raw_message": raw, "font": 0,
               "sender": {"user_id": USER, "nickname": "FLY"}, "anonymous": None}
    else:
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "private", "sub_type": "friend", "message_id": _msg_id,
               "user_id": USER,
               "message": [{"type": "text", "data": {"text": text}}],
               "raw_message": text, "font": 0,
               "sender": {"user_id": USER, "nickname": "FLY"}}
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
        out = {}
        for robot in d.get("robots", []):
            for cc in robot.get("conversation_controllers", []):
                out[cc.get("conversation_key")] = (cc.get("status"), cc.get("processing"), cc.get("pending_count"))
        return out
    except Exception as e:
        return {"error": str(e)}

def log_lines_since(n0):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return f.readlines()[n0:]

print("=" * 60)
print(f"QQ STRESS TEST: {len(MESSAGES)} mixed messages")
print("=" * 60)

with open(LOG, encoding="utf-8", errors="replace") as f:
    log0 = len(f.readlines())
h = login()
t0 = time.time()
sent = []  # (tag, conv, text, sent_at, http)

def sender_thread():
    for delay, conv, text, _ in MESSAGES:
        time.sleep(delay)
        tag = text.split()[0]
        st = send_event(conv, text)
        sent.append({"tag": tag, "conv": conv, "text": text, "at": time.time() - t0, "http": st})
        print(f"[{int(time.time()-t0):4d}s] >>> {conv} '{text[:40]}' -> {st}", flush=True)

st = threading.Thread(target=sender_thread, daemon=True)
st.start()

# monitor while sending + 120s grace
errors_seen = set()
while st.is_alive() or (time.time() - t0) < 130:
    time.sleep(15)
    el = int(time.time() - t0)
    pend = pending_snapshot(h)
    replies = [l for l in log_lines_since(log0) if "QQ [" in l]
    # backend errors in last window
    try:
        logs = subprocess.run(["docker", "logs", "TermPaws-backend-1", "--since", "20s"],
                              capture_output=True, text=True, timeout=20).stdout
        for line in logs.splitlines():
            if ("ERROR" in line or "BadRequest" in line or "Exception" in line) and line not in errors_seen:
                errors_seen.add(line)
                print(f"  [{el}s] [BACKEND-ERR] {line[:160]}", flush=True)
    except Exception:
        pass
    print(f"  [{el:4d}s] replies={len(replies)} pending={pend}", flush=True)
    if not st.is_alive() and el > 130:
        break

# grace period for late replies
print("\n[GRACE] waiting 90s for late replies...")
time.sleep(90)

# ---- report ----
print("\n" + "=" * 60)
print("[REPORT]")
print("=" * 60)
new_lines = log_lines_since(log0)
reply_lines = [l.strip() for l in new_lines if "QQ [" in l]
print(f"sent={len(sent)} replies={len(reply_lines)}")
for l in reply_lines:
    print(f"  {l[:170]}")
pend = pending_snapshot(h)
print(f"\nfinal pending: {pend}")
total_wait = int(time.time() - t0)
print(f"total elapsed: {total_wait}s")
if errors_seen:
    print(f"\nbackend errors captured: {len(errors_seen)}")
    for e in list(errors_seen)[:10]:
        print(f"  {e[:180]}")
print("\n[SCRIPT DONE]")
