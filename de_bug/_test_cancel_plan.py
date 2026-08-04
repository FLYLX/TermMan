"""Simulate QQ: send long multi-step task -> cancel mid-run -> verify plan cleared and NOT revived."""
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

def get_tickets():
    try:
        r = api("get", f"/items/{ITEM}/reply-tickets")
        data = r.json()
        return data if isinstance(data, list) else data.get("tickets", [])
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

        # Task: first step is long (sleep 300), rest are quick
        task_msg = "帮我做三件事：1.后台跑 sleep 300 && echo SLEEP_DONE 2.安装 figlet 3.安装 cowsay。按顺序来，每步完成再下一步"
        log(f"=== Sending task ===")
        await send_qq_msg(ws, task_msg)

        # Wait for plan (up to 90s)
        log("Waiting for plan...")
        plan = []
        for i in range(18):
            await asyncio.sleep(5)
            plan = get_plan()
            if plan:
                log(f"  plan after {(i+1)*5}s:")
                for j, s in enumerate(plan):
                    log(f"    {j+1}. [{s.get('status')}] {s.get('step')}")
                break
            if (i+1) % 4 == 0:
                log(f"  waiting... ({(i+1)*5}s)")

        if not plan:
            # Maybe plan is on a ticket but not exposed via /plan API
            log("No plan via /plan API, checking tickets...")
            tickets = get_tickets()
            for t in tickets[:5]:
                tp = t.get("plan", [])
                log(f"  ticket {t.get('ticket_id','')[:8]}: status={t.get('status')} plan={[(s.get('status'),s.get('step','')[:20]) for s in tp] if tp else '(none)'} req={t.get('request_message','')[:40]}")
            if not any(t.get("plan") for t in tickets):
                log("ERROR: no plan anywhere. Bot responses:")
                for m in received:
                    log(f"  {m[:200]}")
                lt.cancel()
                return
            plan = [t.get("plan") for t in tickets if t.get("plan")][0]
            log(f"Found plan on ticket: {[(s.get('status'),s.get('step','')[:25]) for s in plan]}")

        # Wait for first job to be running, then cancel
        log("Waiting 10s for job to start...")
        await asyncio.sleep(10)
        log("=== Sending cancel ===")
        await send_qq_msg(ws, "取消任务")

        # Monitor plan for 120s
        log("Monitoring plan...")
        cleared_seen = False
        revived = False
        for i in range(24):
            await asyncio.sleep(5)
            plan = get_plan()
            el = (i+1)*5
            if not plan:
                if not cleared_seen:
                    log(f"  [{el}s] plan CLEARED")
                    cleared_seen = True
            else:
                statuses = [(s.get('status'), s.get('step','')[:30]) for s in plan]
                if cleared_seen:
                    log(f"  [{el}s] WARNING: plan REVIVED! {statuses}")
                    revived = True
                else:
                    log(f"  [{el}s] plan: {statuses}")

        lt.cancel()
        log("=== RESULT ===")
        if revived:
            log("FAIL: plan revived after cancel!")
        elif cleared_seen:
            log("PASS: plan cleared and stayed cleared")
        else:
            log("FAIL: plan was never cleared")
        for m in received:
            if "取消" in m or "停止" in m:
                log(f"  bot: {m[:150]}")

asyncio.run(main())
