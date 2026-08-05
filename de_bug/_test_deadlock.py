"""Deadlock repro: long task running + two direct messages -> both answered promptly."""
import asyncio, json, time

WS_URL = "ws://127.0.0.1:33333/onebot/v11/ws"
HEADERS = {
    "X-Self-ID": "10001",
    "X-Client-Role": "Universal",
    "Authorization": "Bearer x0SA-6tPi_ZbWciyKDr7F6e_arctgnMbRRWsK-lwQBs",
}
USER_ID = 2537134688

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

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
        replies = []  # (time, text)
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    m = data.get("params", {}).get("message", "")
                    text = ("".join(s.get("data",{}).get("text","")
                            for s in m if isinstance(s,dict))
                            if isinstance(m, list) else str(m))
                    replies.append((time.time(), text))
                    log(f"  BOT: {text[:150]}")
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        # 1. start long task
        t0 = time.time()
        await send_qq(ws, "后台跑 sleep 120 && echo LONG_TASK_DONE，跑完告诉我")
        log("sent long task (sleep 120)")
        await asyncio.sleep(8)  # let turn 1 start the job

        # 2. two direct messages while turn 1 is in flight
        await send_qq(ws, "1+1等于几")
        log("sent msg A (1+1)")
        await asyncio.sleep(2)
        await send_qq(ws, "2+2等于几")
        log("sent msg B (2+2)")

        # 3. watch replies: A and B should arrive quickly (not after minutes)
        watch_end = time.time() + 100
        while time.time() < watch_end:
            await asyncio.sleep(2)
            texts = [t for _, t in replies]
            if any("2" in t for t in texts) and any("4" in t for t in texts):
                break

        lt.cancel()
        log("=" * 45)
        for ts, text in replies:
            log(f"  +{ts - t0:5.1f}s  {text[:80]}")
        quick = [ts - t0 for ts, t in replies if ("2" in t or "4" in t)]
        if quick and max(quick) < 60:
            log("PASS: direct messages answered promptly while long task ran")
        elif quick:
            log("FAIL: direct messages blocked >60s (deadlock still present)")
        else:
            log("FAIL: no answers to direct messages")

asyncio.run(main())
