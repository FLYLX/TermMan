"""Send 1+1 .. 1+9 rapidly: turn1 answers 2, merged batch should answer 3..10 each."""
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
        replies = []
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    m = data.get("params", {}).get("message", "")
                    text = ("".join(s.get("data",{}).get("text","")
                            for s in m if isinstance(s,dict))
                            if isinstance(m, list) else str(m))
                    replies.append((time.time(), text))
                    log(f"  BOT: {text[:300]}")
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        t0 = time.time()
        for i in range(1, 10):
            await send_qq(ws, f"1+{i}等于几")
            log(f"sent 1+{i}")
            await asyncio.sleep(0.4)

        log("--- watching ---")
        watch_end = time.time() + 180
        while time.time() < watch_end and len(replies) < 2:
            await asyncio.sleep(2)
        await asyncio.sleep(15)
        lt.cancel()

        log("=" * 50)
        log(f"total replies: {len(replies)}")
        for ts, text in replies:
            log(f"  +{ts - t0:5.1f}s  {text[:200]}")
        # check coverage: batch reply should contain answers 3..10
        batch = replies[1][1] if len(replies) > 1 else ""
        covered = [str(n) for n in range(3, 11) if str(n) in batch]
        log(f"batch covers answers 3..10: {len(covered)}/8 -> {covered}")

asyncio.run(main())
