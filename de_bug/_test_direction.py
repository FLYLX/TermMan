"""Test: direction change mid-task."""
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

def api(method, path, **kw):
    r = requests.post(f"{BASE}/api/v1/login/access-token",
        data={"username": "admin@example.com", "password": "changethis"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    kw.setdefault("headers", h)
    kw.setdefault("timeout", 15)
    return getattr(requests, method)(f"{BASE}/api/v1{path}", **kw)

def get_plan():
    try:
        r = api("get", f"/items/{ITEM}/plan")
        return r.json().get("plan", [])
    except:
        return []

def send_qq_msg(ws, text):
    event = {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": int(time.time() * 1000) % 2**31,
        "user_id": USER_ID,
        "message": text,
        "raw_message": text,
        "font": 0,
        "time": int(time.time()),
        "self_id": 10001,
        "sender": {"user_id": USER_ID, "nickname": "测试用户"},
    }
    return ws.send(json.dumps(event))

async def main():
    import websockets

    async with websockets.connect(WS_URL, additional_headers=HEADERS, ping_interval=20, ping_timeout=10) as ws:
        log("WS connected")

        received = []
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                action = data.get("action", "")
                echo = data.get("echo", "")
                if "send" in action:
                    params = data.get("params", {})
                    m = params.get("message", "")
                    if isinstance(m, list):
                        msg_text = "".join(seg.get("data",{}).get("text","") for seg in m if isinstance(seg,dict))
                    else:
                        msg_text = str(m)
                    log(f"  BOT->QQ: {msg_text[:250]}")
                    received.append(msg_text)
                    await ws.send(json.dumps({"status": "ok", "retcode": 0, "data": {"message_id": int(time.time())}, "echo": echo}))
        lt = asyncio.create_task(listener())

        # Step 1: Start long task
        log("Sending: 后台跑 sleep 300 && echo LONG_DONE")
        await send_qq_msg(ws, "帮我后台跑 sleep 300 && echo LONG_DONE，跑完告诉我")

        # Wait for job to start
        log("Waiting 15s for job to start...")
        await asyncio.sleep(15)

        # Check plan
        plan = get_plan()
        if plan:
            log(f"  initial plan: {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")
        else:
            log("  (no plan yet)")

        # Step 2: Change direction
        log("Sending direction change: 别跑sleep了，装figlet和cowsay")
        await send_qq_msg(ws, "别跑 sleep 了，帮我装 figlet 和 cowsay，装完验证")

        # Step 3: Monitor plan adaptation for 180s
        log("Monitoring plan adaptation...")
        cleared = False
        revived_after_clear = False
        old_plan_seen = False
        new_plan_seen = False
        for i in range(36):
            await asyncio.sleep(5)
            plan = get_plan()
            el = (i+1)*5
            if not plan:
                if not cleared:
                    log(f"  [{el}s] plan CLEARED")
                    cleared = True
            else:
                steps = [(s.get('status'), s.get('step','')[:30]) for s in plan]
                has_sleep = any("sleep" in s[1].lower() for s in steps)
                has_figlet = any("figlet" in s[1].lower() for s in steps)
                if has_sleep and not has_figlet:
                    if not old_plan_seen:
                        log(f"  [{el}s] old plan (sleep): {steps}")
                        old_plan_seen = True
                elif has_figlet:
                    if not new_plan_seen:
                        log(f"  [{el}s] new plan (figlet/cowsay): {steps}")
                        new_plan_seen = True
                    else:
                        log(f"  [{el}s] plan: {steps}")
                else:
                    log(f"  [{el}s] plan: {steps}")
                if cleared:
                    revived_after_clear = True
                    log(f"  [{el}s] WARNING: revived after clear!")

        lt.cancel()
        log("=== RESULT ===")
        if revived_after_clear:
            log("FAIL: plan revived after being cleared")
        elif new_plan_seen:
            log("PASS: plan adapted to new direction")
        else:
            log("PARTIAL: no clear plan adaptation observed")
        for m in received:
            log(f"  bot: {m[:150]}")

asyncio.run(main())
