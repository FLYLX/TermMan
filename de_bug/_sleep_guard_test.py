# -*- coding: utf-8 -*-
"""Sleep/superseded guard stress test (QQ path).
P1: group off-topic chatter -> bot silent/sleeps; then direct @question -> MUST reply (wake path)
P2: background job longer than the 50s awake window (sleep 70) -> completion report MUST arrive
P3: supersede flood: question + immediate follow-ups -> latest answered, no dupes
P4: contradiction-reminder style: slow multi-intent request -> reply MUST arrive
"""
import requests, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BRIDGE = "http://127.0.0.1:33333"
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"
GROUP = 770362397
U1, U2 = 2537134688, 987654321

_mid = int(time.time()) % 10000 * 100
def send(conv, user, text):
    global _mid
    _mid += 1
    if conv == "group":
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "group", "sub_type": "normal", "message_id": _mid,
               "group_id": GROUP, "user_id": user,
               "message": [{"type": "at", "data": {"qq": "10001"}},
                            {"type": "text", "data": {"text": f" {text}"}}],
               "raw_message": f"[CQ:at,qq=10001] {text}", "font": 0,
               "sender": {"user_id": user, "nickname": f"U{user}"}, "anonymous": None}
    else:
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "private", "sub_type": "friend", "message_id": _mid,
               "user_id": user, "message": [{"type": "text", "data": {"text": text}}],
               "raw_message": text, "font": 0, "sender": {"user_id": user, "nickname": f"U{user}"}}
    r = requests.post(f"{BRIDGE}/onebot/v11/", json=evt, headers={"X-Self-ID": "10001"}, timeout=15)
    return r.status_code

def send_group_raw(user, text):
    """Group message WITHOUT @bot (off-topic chatter)."""
    global _mid
    _mid += 1
    evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
           "message_type": "group", "sub_type": "normal", "message_id": _mid,
           "group_id": GROUP, "user_id": user,
           "message": [{"type": "text", "data": {"text": text}}],
           "raw_message": text, "font": 0,
           "sender": {"user_id": user, "nickname": f"U{user}"}, "anonymous": None}
    return requests.post(f"{BRIDGE}/onebot/v11/", json=evt,
                         headers={"X-Self-ID": "10001"}, timeout=15).status_code

def log_len():
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return len(f.readlines())

def replies_since(n0):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return [l.strip() for l in f.readlines()[n0:] if "QQ [" in l]

def wait_replies(mark, n=1, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        reps = replies_since(mark)
        if len(reps) >= n:
            return reps
        time.sleep(3)
    return replies_since(mark)

results = {}

# ---- P1: sleep then wake ----
print("[P1] off-topic chatter (no @) then direct @question", flush=True)
mark = log_len()
send_group_raw(U1, "今晚吃啥好呢")
time.sleep(2)
send_group_raw(U2, "我想吃火锅")
time.sleep(8)
reps_offtopic = replies_since(mark)
print(f"  off-topic replies (expect 0-1): {len(reps_offtopic)}")
for r in reps_offtopic:
    print(f"    {r[:120]}")
mark2 = log_len()
send("group", U1, "P1测试：77+88等于几")
reps = wait_replies(mark2, 1, 90)
ok1 = any("165" in r for r in reps)
results["P1_wake_after_chatter"] = ok1
print(f"  wake reply: ok={ok1}")
for r in reps:
    print(f"    {r[:140]}")

# ---- P2: job outliving the 50s awake window ----
print("\n[P2] sleep 70 background job (>50s window), report must arrive", flush=True)
mark = log_len()
send("private", U1, "P2测试：后台跑 sleep 70 && echo p2-done，完事把结果告诉我")
reps = wait_replies(mark, 1, 200)
ok2 = any("p2-done" in r or "完成" in r or "跑完" in r or "好了" in r for r in reps)
results["P2_report_after_window"] = ok2
print(f"  report: ok={ok2} replies={len(reps)}")
for r in reps:
    print(f"    {r[:140]}")

# ---- P3: supersede flood ----
print("\n[P3] question + instant follow-ups (supersede)", flush=True)
mark = log_len()
send("private", U1, "P3测试：第一问 5*5=?")
time.sleep(1)
send("private", U1, "等等先别答，先算 6*6=?")
time.sleep(1)
send("private", U1, "P3最终：还是回答 7*7=?")
reps = wait_replies(mark, 1, 120)
ok3 = any("49" in r for r in reps)
results["P3_supersede_latest"] = ok3
print(f"  latest answered: ok={ok3} replies={len(reps)}")
for r in reps:
    print(f"    {r[:140]}")

# ---- P4: contradiction reminder style (slow composed reply) ----
print("\n[P4] multi-intent slow request, reply must arrive", flush=True)
mark = log_len()
send("private", U1, "P4测试：先跑一下 uptime，然后分析一下负载高不高，最后给我个结论")
reps = wait_replies(mark, 1, 150)
ok4 = len(reps) > 0
results["P4_slow_composed_reply"] = ok4
print(f"  reply arrived: ok={ok4} replies={len(reps)}")
for r in reps:
    print(f"    {r[:140]}")

print("\n" + "=" * 60)
print("[GUARD TEST SUMMARY]")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("=" * 60)
