# -*- coding: utf-8 -*-
"""Stress test for qwen3.8-max-preview channel: concurrent senders through full QQ chain."""
import requests, time, json, threading, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ROBOT_ID = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"

# (sender_id, question, expected answer string)
WAVES = [
    [
        ("90001", "口算：17+25等于？只回答数字，不要用工具", "42"),
        ("90002", "口算：63-28等于？只回答数字，不要用工具", "35"),
        ("90003", "口算：12*9等于？只回答数字，不要用工具", "108"),
        ("90004", "口算：144/12等于？只回答数字，不要用工具", "12"),
        ("90005", "口算：37+48等于？只回答数字，不要用工具", "85"),
        ("90006", "口算：91-56等于？只回答数字，不要用工具", "35"),
        ("90007", "口算：15*7等于？只回答数字，不要用工具", "105"),
        ("90008", "口算：225/15等于？只回答数字，不要用工具", "15"),
    ],
    [
        ("90011", "口算：56+37等于？只回答数字，不要用工具", "93"),
        ("90012", "口算：82-49等于？只回答数字，不要用工具", "33"),
        ("90013", "口算：13*11等于？只回答数字，不要用工具", "143"),
        ("90014", "口算：196/14等于？只回答数字，不要用工具", "14"),
        ("90015", "口算：68+77等于？只回答数字，不要用工具", "145"),
        ("90016", "口算：120-63等于？只回答数字，不要用工具", "57"),
        ("90017", "口算：16*8等于？只回答数字，不要用工具", "128"),
        ("90018", "口算：324/18等于？只回答数字，不要用工具", "18"),
    ],
]

def dispatch(sender_id, text):
    payload = {
        "sender_key": f"private_{sender_id}",
        "text": text,
        "reply_target": {
            "target_type": "private",
            "target_id": sender_id,
            "metadata": {"sender_name": f"stress_{sender_id}", "sender_id": sender_id, "conversation_type": "private"},
        },
    }
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/v1/robots/{ROBOT_ID}/dispatch", json=payload,
                          headers={"X-TermPaws-Bridge-Token": BRIDGE_TOKEN}, timeout=30)
        return r.status_code, r.text[:120], time.time() - t0
    except Exception as e:
        return 0, str(e)[:120], time.time() - t0

def read_replies():
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        m = re.match(r"\[(\d\d):(\d\d):(\d\d)\] QQ \[send_private_msg\] -> (\d+): (.*)", line.strip())
        if m:
            h, mi, s, target, text = m.groups()
            out.append({"ts": int(h) * 3600 + int(mi) * 60 + int(s), "target": target, "text": text})
    return out

def run_wave(wave, wave_no, deadline_wait=240):
    print(f"\n{'='*60}\nWAVE {wave_no}: {len(wave)} concurrent senders\n{'='*60}", flush=True)
    log_before = len(read_replies())
    dispatch_at = {}
    results = []

    def fire(sender_id, question, expected, delay):
        time.sleep(delay)
        status, body, elapsed = dispatch(sender_id, question)
        dispatch_at[sender_id] = time.time()
        results.append((sender_id, status, round(elapsed, 1)))
        print(f"  dispatch {sender_id}: status={status} ({elapsed:.1f}s) {body[:80]}", flush=True)

    threads = [threading.Thread(target=fire, args=(s, q, e, i * 0.5)) for i, (s, q, e) in enumerate(wave)]
    t_start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # wait for replies
    expected_by_sender = {s: e for s, _, e in wave}
    matched = {}
    while time.time() - t_start < deadline_wait:
        time.sleep(5)
        replies = read_replies()[log_before:]
        for reply in replies:
            if reply["target"] in matched:
                continue
            for sender_id, expected in expected_by_sender.items():
                if sender_id in matched:
                    continue
                if reply["target"] == sender_id:
                    matched[sender_id] = reply
                    break
        if len(matched) >= len(wave):
            break
        print(f"  [{int(time.time()-t_start):3d}s] replies={len(matched)}/{len(wave)}", flush=True)

    ok = bad = 0
    for sender_id, question, expected in wave:
        reply = matched.get(sender_id)
        if reply is None:
            print(f"  {sender_id}: NO REPLY (expected {expected})", flush=True)
            bad += 1
            continue
        correct = expected in reply["text"]
        channel_error = ("通道" in reply["text"]) or ("channel" in reply["text"].lower()) or ("ServiceUnavailable" in reply["text"])
        latency = ""
        if sender_id in dispatch_at:
            latency = f" latency~{max(0, reply['ts'] - (dispatch_at[sender_id] % 86400)):.0f}s"
        if channel_error:
            print(f"  {sender_id}: CHANNEL ERROR -> {reply['text'][:100]}", flush=True)
            bad += 1
        elif correct:
            print(f"  {sender_id}: OK ({expected}){latency} -> {reply['text'][:60]}", flush=True)
            ok += 1
        else:
            print(f"  {sender_id}: WRONG (expected {expected}){latency} -> {reply['text'][:80]}", flush=True)
            bad += 1
    print(f"WAVE {wave_no} RESULT: ok={ok} bad={bad} total={len(wave)} elapsed={int(time.time()-t_start)}s", flush=True)
    return ok, bad

total_ok = total_bad = 0
for i, wave in enumerate(WAVES, 1):
    ok, bad = run_wave(wave, i)
    total_ok += ok
    total_bad += bad
    if i < len(WAVES):
        time.sleep(10)

print(f"\n{'='*60}\nFINAL: ok={total_ok} bad={total_bad} total={total_ok+total_bad}\n{'='*60}", flush=True)
print("[SCRIPT DONE]", flush=True)