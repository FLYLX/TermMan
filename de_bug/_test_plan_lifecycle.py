"""Test: 1) plan auto-clears on completion 2) cancel clears plan, no revival."""
import asyncio, json, time, requests

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
WS_URL = "ws://127.0.0.1:33333/onebot/v11/ws"
HEADERS = {
    "X-Self-ID": "10001",
    "X-Client-Role": "Universal",
    "Authorization": "Bearer x0SA-6tPi_ZbWciyKDr7F6e_arctgnMbRRWsK-lwQBs",
}
USER_ID = 2537134688

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def _headers():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
        data={"username": "admin@example.com", "password": "changethis"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def get_plan():
    try:
        r = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=_headers(), timeout=15)
        return r.json().get("plan", [])
    except:
        return []

def send_qq(ws, text):
    return ws.send(json.dumps({
        "post_type": "message", "message_type": "private", "sub_type": "friend",
        "message_id": int(time.time() * 1000) % 2**31,
        "user_id": USER_ID, "message": text, "raw_message": text, "font": 0,
        "time": int(time.time()), "self_id": 10001,
        "sender": {"user_id": USER_ID, "nickname": "测试用户"},
    }))

async def main():
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        log("WS connected")
        received = []
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    m = data.get("params", {}).get("message", "")
                    text = ("".join(s.get("data",{}).get("text","")
                            for s in m if isinstance(s,dict))
                            if isinstance(m, list) else str(m))
                    log(f"  BOT: {text[:180]}")
                    received.append(text)
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        # ===== TEST 1: plan auto-clears on completion =====
        log("=" * 50)
        log("TEST 1: multi-step task -> plan should AUTO-CLEAR when done")
        log("=" * 50)
        await send_qq(ws, "帮我做两件事：1.后台跑 sleep 5 && echo STEP1 2.后台跑 sleep 5 && echo STEP2，按顺序，都跑完告诉我")

        plan_seen = False
        plan_cleared = False
        for i in range(36):  # 3 min
            await asyncio.sleep(5)
            plan = get_plan()
            el = (i+1)*5
            if plan:
                plan_seen = True
                log(f"  [{el}s] plan: {[(s.get('status'), s.get('step','')[:25]) for s in plan]}")
            else:
                if plan_seen and not plan_cleared:
                    log(f"  [{el}s] plan AUTO-CLEARED")
                    plan_cleared = True
                    break
                elif not plan_seen:
                    log(f"  [{el}s] waiting for plan...")

        t1_pass = plan_seen and plan_cleared
        log(f"TEST 1: {'PASS' if t1_pass else 'FAIL'} (plan_seen={plan_seen}, auto_cleared={plan_cleared})")

        await asyncio.sleep(10)

        # ===== TEST 2: cancel clears plan, no revival =====
        log("=" * 50)
        log("TEST 2: cancel mid-task -> plan cleared, NO revival")
        log("=" * 50)
        await send_qq(ws, "帮我后台跑 sleep 300 && echo NEVER_FINISH")

        plan2_seen = False
        for i in range(12):
            await asyncio.sleep(5)
            plan = get_plan()
            if plan:
                plan2_seen = True
                log(f"  plan: {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")
                break
        if not plan2_seen:
            log("  (no plan created for single-step task, checking tickets...)")


        await asyncio.sleep(5)
        log("sending cancel...")
        await send_qq(ws, "取消任务")

        cleared2 = False
        revived = False
        for i in range(18):  # 90s
            await asyncio.sleep(5)
            plan = get_plan()
            el = (i+1)*5
            if not plan:
                if not cleared2:
                    log(f"  [{el}s] plan CLEARED")
                    cleared2 = True
            else:
                if cleared2:
                    log(f"  [{el}s] REVIVED! {[(s.get('status'), s.get('step','')[:25]) for s in plan]}")
                    revived = True
                else:
                    log(f"  [{el}s] still exists: {[(s.get('status'), s.get('step','')[:25]) for s in plan]}")

        t2_pass = cleared2 and not revived
        log(f"TEST 2: {'PASS' if t2_pass else 'FAIL'} (cleared={cleared2}, revived={revived})")

        lt.cancel()
        log("=" * 50)
        log("FINAL")
        log("=" * 50)
        log(f"  auto-clear on completion: {'PASS' if t1_pass else 'FAIL'}")
        log(f"  cancel clears, no revival: {'PASS' if t2_pass else 'FAIL'}")

asyncio.run(main())
