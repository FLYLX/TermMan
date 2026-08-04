"""Test: parallel tasks + cancel -> new task."""
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

        # ===== TEST 2: parallel tasks =====
        log("=" * 50)
        log("TEST 2: parallel tasks (sleep 30 + sleep 45)")
        log("=" * 50)
        await send_qq_msg(ws, "帮我同时做两件事：1.后台跑 sleep 30 && echo P1_DONE 2.后台跑 sleep 45 && echo P2_DONE。两个并行跑，都跑完告诉我")

        plan = []
        for i in range(18):
            await asyncio.sleep(5)
            plan = get_plan()
            if plan:
                log(f"  plan after {(i+1)*5}s: {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")
                break
        if not plan:
            log("  (no plan created)")
        else:
            log("  monitoring parallel execution...")
            for i in range(24):
                await asyncio.sleep(5)
                plan = get_plan()
                el = (i+1)*5
                if not plan:
                    log(f"  [{el}s] plan CLEARED (all done)")
                    break
                else:
                    log(f"  [{el}s] {[(s.get('status'), s.get('step','')[:25]) for s in plan]}")

        await asyncio.sleep(5)

        # ===== TEST 3: cancel -> new task =====
        log("=" * 50)
        log("TEST 3: cancel long task -> new task")
        log("=" * 50)
        await send_qq_msg(ws, "帮我后台跑 sleep 300 && echo OLD_TASK_DONE")
        log("Sent: long sleep 300")

        plan = []
        for i in range(12):
            await asyncio.sleep(5)
            plan = get_plan()
            if plan:
                log(f"  plan: {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")
                break

        await asyncio.sleep(8)
        log("Sending cancel...")
        await send_qq_msg(ws, "取消任务")

        # Wait for clear
        cleared = False
        for i in range(12):
            await asyncio.sleep(5)
            plan = get_plan()
            if not plan:
                cleared = True
                log(f"  plan cleared after {(i+1)*5}s")
                break
        if not cleared:
            log("  WARNING: plan not cleared")

        # New task immediately
        await asyncio.sleep(2)
        log("Sending new task: install sl")
        await send_qq_msg(ws, "帮我安装 sl 命令行小火车，装完跑一下验证")

        # Monitor
        revived = False
        new_done = False
        for i in range(24):
            await asyncio.sleep(5)
            plan = get_plan()
            el = (i+1)*5
            if not plan:
                if not new_done:
                    log(f"  [{el}s] plan CLEARED")
                    new_done = True
            else:
                steps = [(s.get('status'), s.get('step','')[:25]) for s in plan]
                has_old = any("sleep" in s[1].lower() or "old" in s[1].lower() for s in steps)
                has_new = any("sl" in s[1].lower() for s in steps)
                if has_old and cleared:
                    log(f"  [{el}s] WARNING: old plan revived! {steps}")
                    revived = True
                elif has_new:
                    log(f"  [{el}s] new plan: {steps}")
                else:
                    log(f"  [{el}s] plan: {steps}")

        lt.cancel()
        log("=" * 50)
        log("RESULTS")
        log("=" * 50)
        log(f"  parallel: see above")
        log(f"  cancel->new: {'FAIL (old plan revived)' if revived else 'PASS (old plan did not interfere)'}")
        for m in received:
            log(f"  bot: {m[:150]}")

asyncio.run(main())
