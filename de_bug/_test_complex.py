"""Complex QQ simulation tests: direction change, parallel tasks, multi-target notify."""
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

async def wait_for_plan(ws, timeout_s=120, poll_s=5):
    """Wait for a plan to appear, return it."""
    for i in range(timeout_s // poll_s):
        await asyncio.sleep(poll_s)
        plan = get_plan()
        if plan:
            return plan
    return []

async def monitor_plan(ws, duration_s=120, poll_s=5, label=""):
    """Monitor plan changes for a duration, log transitions."""
    seen_states = set()
    cleared = False
    revived = False
    for i in range(duration_s // poll_s):
        await asyncio.sleep(poll_s)
        plan = get_plan()
        el = (i+1)*poll_s
        if not plan:
            if not cleared:
                log(f"  [{label} {el}s] plan CLEARED")
                cleared = True
        else:
            key = tuple((s.get('status'), s.get('step','')[:20]) for s in plan)
            if cleared:
                log(f"  [{label} {el}s] REVIVED! {[ (s.get('status'), s.get('step','')[:25]) for s in plan]}")
                revived = True
            elif key not in seen_states:
                seen_states.add(key)
                log(f"  [{label} {el}s] plan: {[(s.get('status'), s.get('step','')[:25]) for s in plan]}")
    return cleared, revived

async def test_direction_change(ws, listener_task):
    """Test: start long task -> change direction mid-way -> verify plan adapts."""
    log("=" * 60)
    log("TEST 1: mid-direction change (sleep 300 -> install figlet instead)")
    log("=" * 60)

    # Step 1: Start a long task
    await send_qq_msg(ws, "帮我后台跑 sleep 300 && echo LONG_DONE，跑完告诉我")
    log("Sent: long sleep task")

    plan = await wait_for_plan(ws, timeout_s=60)
    if plan:
        log(f"  initial plan: {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")
    else:
        log("  (no plan, task may be single-step)")

    # Step 2: Change direction
    await asyncio.sleep(10)
    log("Sending direction change...")
    await send_qq_msg(ws, "别跑 sleep 了，帮我装 figlet 和 cowsay，装完验证")

    # Step 3: Monitor plan - should adapt to new direction
    log("Monitoring plan adaptation...")
    cleared, revived = await monitor_plan(ws, duration_s=180, label="T1")

    log(f"TEST 1 result: cleared={cleared} revived={revived}")
    return not revived

async def test_parallel_tasks(ws, listener_task):
    """Test: two independent tasks in one message -> parallel execution."""
    log("=" * 60)
    log("TEST 2: parallel independent tasks")
    log("=" * 60)

    await send_qq_msg(ws, "帮我同时做两件事：1.后台跑 sleep 30 && echo P1_DONE 2.后台跑 sleep 45 && echo P2_DONE。两个并行跑")
    log("Sent: parallel tasks")

    plan = await wait_for_plan(ws, timeout_s=60)
    if plan:
        log(f"  plan: {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")
    else:
        log("  (no plan created)")

    log("Monitoring parallel execution...")
    cleared, revived = await monitor_plan(ws, duration_s=120, label="T2")

    log(f"TEST 2 result: cleared={cleared} revived={revived}")
    return not revived

async def test_cancel_then_new_task(ws, listener_task):
    """Test: cancel task -> immediately send new task -> old plan doesn't interfere."""
    log("=" * 60)
    log("TEST 3: cancel -> new task (old plan must not interfere)")
    log("=" * 60)

    # Start long task
    await send_qq_msg(ws, "帮我后台跑 sleep 300 && echo OLD_TASK")
    log("Sent: long task")
    plan = await wait_for_plan(ws, timeout_s=60)
    if plan:
        log(f"  initial plan: {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")

    # Cancel
    await asyncio.sleep(8)
    log("Sending cancel...")
    await send_qq_msg(ws, "取消任务")

    # Wait for plan to clear
    plan_cleared = False
    for i in range(12):
        await asyncio.sleep(5)
        plan = get_plan()
        if not plan:
            plan_cleared = True
            log(f"  plan cleared after {(i+1)*5}s")
            break
    if not plan_cleared:
        log("  WARNING: plan not cleared after 60s")

    # Immediately send new task
    await asyncio.sleep(2)
    log("Sending new task...")
    await send_qq_msg(ws, "帮我安装 sl 这个命令行小火车，装完跑一下验证")

    # Monitor - new plan should appear and complete without old plan interfering
    log("Monitoring new task...")
    cleared, revived = await monitor_plan(ws, duration_s=150, label="T3")

    log(f"TEST 3 result: cleared={cleared} revived={revived}")
    return not revived

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

        results = {}

        # Wait between tests to let previous state settle
        log("\n>>> Starting TEST 1: direction change")
        results["direction_change"] = await test_direction_change(ws, lt)
        await asyncio.sleep(10)

        log("\n>>> Starting TEST 2: parallel tasks")
        results["parallel"] = await test_parallel_tasks(ws, lt)
        await asyncio.sleep(10)

        log("\n>>> Starting TEST 3: cancel -> new task")
        results["cancel_then_new"] = await test_cancel_then_new_task(ws, lt)

        lt.cancel()

        log("\n" + "=" * 60)
        log("FINAL RESULTS")
        log("=" * 60)
        for name, passed in results.items():
            status = "PASS" if passed else "FAIL"
            log(f"  {name}: {status}")

asyncio.run(main())
