"""Mixed sources: QQ + web messages while busy -> replies routed to correct places."""
import asyncio, json, time, requests, threading

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

def send_web(text):
    def _do():
        try:
            r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
                json={"message": text, "history": []},
                headers={**_headers(), "Content-Type": "application/json"},
                timeout=180)
            content = r.json().get("content", "")
            web_replies.append((time.time(), content))
            log(f"  WEB-REPLY: {content[:150]}")
        except Exception as e:
            log(f"  web err: {e}")
    threading.Thread(target=_do, daemon=True).start()

web_replies = []
qq_replies = []

async def main():
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        log("WS connected")
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    m = data.get("params", {}).get("message", "")
                    text = ("".join(s.get("data",{}).get("text","")
                            for s in m if isinstance(s,dict))
                            if isinstance(m, list) else str(m))
                    qq_replies.append((time.time(), text))
                    log(f"  QQ-REPLY: {text[:150]}")
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        def send_qq(text):
            return ws.send(json.dumps({
                "post_type":"message","message_type":"private","sub_type":"friend",
                "message_id":int(time.time()*1000)%2**31,
                "user_id":USER_ID,"message":text,"raw_message":text,"font":0,
                "time":int(time.time()),"self_id":10001,
                "sender":{"user_id":USER_ID,"nickname":"测试用户"},
            }))

        t0 = time.time()
        # QQ first message (starts turn)
        await send_qq("1+1等于几")
        log("sent QQ: 1+1")
        await asyncio.sleep(1)
        # QQ follow-ups
        await send_qq("2+2等于几")
        log("sent QQ: 2+2")
        await send_qq("3+3等于几")
        log("sent QQ: 3+3")
        # web message mixed in
        send_web("4+4等于几")
        log("sent WEB: 4+4")
        await asyncio.sleep(1)
        await send_qq("5+5等于几")
        log("sent QQ: 5+5")
        send_web("6+6等于几")
        log("sent WEB: 6+6")

        # watch
        watch_end = time.time() + 180
        while time.time() < watch_end and (len(qq_replies) < 2 or len(web_replies) < 2):
            await asyncio.sleep(2)
        await asyncio.sleep(10)
        lt.cancel()

        log("=" * 50)
        log(f"QQ replies: {len(qq_replies)} | web replies: {len(web_replies)}")
        for ts, t in qq_replies:
            log(f"  QQ  +{ts-t0:5.1f}s  {t[:100]}")
        for ts, t in web_replies:
            log(f"  WEB +{ts-t0:5.1f}s  {t[:100]}")

asyncio.run(main())
