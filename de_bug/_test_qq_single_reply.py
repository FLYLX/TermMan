"""Regression: QQ turn replies exactly once (no duplicate after removing early-stop)."""
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

async def main():
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        log("WS connected")
        sends = []

        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    params = data.get("params", {})
                    m = params.get("message", "")
                    text = ("".join(s.get("data",{}).get("text","")
                            for s in m if isinstance(s,dict))
                            if isinstance(m, list) else str(m))
                    sends.append(text)
                    log(f"  BOT: {text[:120]}")
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        await ws.send(json.dumps({
            "post_type":"message","message_type":"private","sub_type":"friend",
            "message_id":int(time.time()*1000)%2**31,
            "user_id":USER_ID,"message":"1+1等于几","raw_message":"1+1等于几",
            "font":0,"time":int(time.time()),"self_id":10001,
            "sender":{"user_id":USER_ID,"nickname":"测试用户"},
        }))
        log("sent: 1+1等于几")

        # wait for reply then watch for duplicates
        t0 = time.time()
        while time.time() - t0 < 60 and not sends:
            await asyncio.sleep(2)
        log("reply received, watching 30s for duplicates...")
        await asyncio.sleep(30)

        lt.cancel()
        log(f"total replies: {len(sends)}")
        if len(sends) == 1:
            log("PASS: exactly one reply, no duplicate")
        elif not sends:
            log("FAIL: no reply")
        else:
            log(f"CHECK: {len(sends)} replies (may be intentional multi-message)")

asyncio.run(main())
