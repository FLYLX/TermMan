"""Test: version direction change + multi-target notification (server + QQ)."""
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

        # ===== TEST 4: version direction change =====
        log("=" * 50)
        log("TEST 4: version direction change")
        log("=" * 50)
        # Start a long task that will be redirected
        await send_qq_msg(ws, "帮我后台跑 sleep 120 && echo V21_DONE，模拟装Java21")
        log("Sent: mock Java21 install (sleep 120)")

        # Wait for it to start
        for i in range(12):
            await asyncio.sleep(5)
            plan = get_plan()
            if plan:
                log(f"  plan: {[(s.get('status'), s.get('step','')[:35]) for s in plan]}")
                break

        # Change direction
        await asyncio.sleep(8)
        log("Sending direction change: 别装21了，装17")
        await send_qq_msg(ws, "别装 21 了，改装 Java 17，装完验证 java -version")

        # Monitor plan adaptation
        adapted = False
        completed = False
        for i in range(36):
            await asyncio.sleep(5)
            plan = get_plan()
            el = (i+1)*5
            if not plan:
                if not completed:
                    log(f"  [{el}s] plan CLEARED (done)")
                    completed = True
                    break
            else:
                steps = [(s.get('status'), s.get('step','')[:35]) for s in plan]
                has_17 = any("17" in s[1] for s in steps)
                if has_17 and not adapted:
                    log(f"  [{el}s] plan adapted to 17: {steps}")
                    adapted = True
                elif el % 15 == 0:
                    log(f"  [{el}s] {steps}")

        await asyncio.sleep(10)

        # ===== TEST 5: multi-target notification =====
        log("=" * 50)
        log("TEST 5: task done -> notify server + QQ")
        log("=" * 50)
        await send_qq_msg(ws, "帮我后台跑 sleep 5 && echo NOTIFY_TEST，跑完之后：1.在服务器控制台说'任务完成了' 2.在QQ告诉我结果")
        log("Sent: task + notify server + QQ")

        # Monitor
        server_notified = False
        qq_notified = False
        for i in range(24):
            await asyncio.sleep(5)
            plan = get_plan()
            el = (i+1)*5
            if not plan:
                if not completed:
                    log(f"  [{el}s] plan done")
            else:
                if el % 15 == 0:
                    log(f"  [{el}s] {[(s.get('status'), s.get('step','')[:30]) for s in plan]}")

        # Check bot responses for evidence of server notification
        for m in received:
            if "服务器" in m or "控制台" in m or "say" in m.lower():
                server_notified = True
            if "NOTIFY_TEST" in m or "完成" in m or "跑完" in m:
                qq_notified = True

        lt.cancel()
        log("=" * 50)
        log("RESULTS")
        log("=" * 50)
        log(f"  direction change: {'PASS' if adapted else 'CHECK'}")
        log(f"  server notified: {server_notified}")
        log(f"  qq notified: {qq_notified}")
        log(f"  total bot messages: {len(received)}")
        for m in received[-8:]:
            log(f"  bot: {m[:180]}")

asyncio.run(main())
