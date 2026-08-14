# -*- coding: utf-8 -*-
"""Full MC lifecycle on BOTH QQ and web channels; verify plan visibility + stages."""
import requests, time, subprocess, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
BRIDGE = "http://127.0.0.1:33333"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
LOG = r"E:\dev\TermPaws\dev\TermPaws\de_bug\_mock_qq.log"
MSG = "安装java，然后装个1.20.1的服务器，跑完去服务器里面发个你好，然后关掉服务器，配置一下jvm和视距低一点，然后重启"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def dexec(cmd):
    p = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "bash", "-c", cmd],
                       capture_output=True, timeout=20)
    return (p.stdout.decode("utf-8", errors="replace") + p.stderr.decode("utf-8", errors="replace")).strip()

def get_plan(h):
    return requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10).json().get("plan", [])

def run_phase(h, channel, timeout_s=1500):
    print(f"\n{'='*60}\n[{channel}] {MSG[:40]}...\n{'='*60}", flush=True)
    mark = len(open(LOG, encoding="utf-8", errors="replace").readlines())
    if channel == "QQ":
        evt = {"time": int(time.time()), "self_id": 10001, "post_type": "message",
               "message_type": "private", "sub_type": "friend", "message_id": int(time.time()) % 100000,
               "user_id": 2537134688,
               "message": [{"type": "text", "data": {"text": MSG}}],
               "raw_message": MSG, "font": 0,
               "sender": {"user_id": 2537134688, "nickname": "FLY"}}
        requests.post(f"{BRIDGE}/onebot/v11/", json=evt, headers={"X-Self-ID": "10001"}, timeout=15)
    else:
        requests.post(f"{BASE}/api/v1/chat/{ITEM}/stream",
                      json={"message": MSG, "history": []}, headers=h, stream=True, timeout=30)
    t0 = time.time()
    seen_plan_at = None
    stage = {"java": False, "up": False, "hello": False, "down": False, "conf": False, "reup": False}
    LOGP = "/app/src/workdir/*/*/app/items/5/mc-server/logs/latest.log"
    while time.time() - t0 < timeout_s:
        time.sleep(20)
        el = int(time.time() - t0)
        plan = get_plan(h)
        if plan and seen_plan_at is None:
            seen_plan_at = el
            print(f"[{el}s] PLAN {len(plan)}步: {[s['step'][:14] for s in plan]}", flush=True)
        if not stage["java"] and "openjdk" in dexec("java -version 2>&1 | head -1"):
            stage["java"] = True; print(f"[{el}s] java就位", flush=True)
        log = dexec(f"tail -30 {LOGP} 2>/dev/null")
        if not stage["up"] and "Done" in log:
            stage["up"] = True; print(f"[{el}s] 服务器Done", flush=True)
        if not stage["hello"] and ("[Server] 你好" in log or "say 你好" in log or "> 你好" in log):
            stage["hello"] = True; print(f"[{el}s] 你好在控制台", flush=True)
        procs = dexec("ps aux | grep -c '[s]erver.jar'").strip()
        if stage["up"] and not stage["down"] and procs == "0":
            stage["down"] = True; print(f"[{el}s] 服务器已关", flush=True)
        if stage["down"] and not stage["conf"]:
            props = dexec("grep view-distance /app/src/workdir/*/*/app/items/5/mc-server/server.properties 2>/dev/null")
            if props:
                stage["conf"] = True; print(f"[{el}s] 配置: {props}", flush=True)
        if stage["down"] and not stage["reup"] and procs != "0":
            stage["reup"] = True; print(f"[{el}s] 服务器已重启", flush=True)
        print(f"[{el}s] plan={len(plan)} {stage}", flush=True)
        if all(stage.values()):
            break
    print(f"[{channel}] plan首次出现: {seen_plan_at}s | stages: {stage}", flush=True)
    return seen_plan_at, stage

h = login()
requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h, timeout=30)
time.sleep(2)

p1, s1 = run_phase(h, "QQ")
p2, s2 = run_phase(h, "WEB")
print("\n===== 汇总 =====")
print(f"QQ : plan@{p1}s stages={s1}")
print(f"WEB: plan@{p2}s stages={s2}")
