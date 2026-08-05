"""Verify: job output goes to .jobs.log, PTY log stays clean."""
import asyncio, json, time, requests, subprocess

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

async def main():
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        log("WS connected")
        done = asyncio.Event()
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    m = data.get("params", {}).get("message", "")
                    text = ("".join(s.get("data",{}).get("text","")
                            for s in m if isinstance(s,dict))
                            if isinstance(m, list) else str(m))
                    log(f"  BOT: {text[:150]}")
                    done.set()
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        # job with apt-style noise output
        await ws.send(json.dumps({
            "post_type":"message","message_type":"private","sub_type":"friend",
            "message_id":int(time.time()*1000)%2**31,
            "user_id":USER_ID,
            "message":"后台跑这个：apt-get update 2>&1 | head -20; echo JOB_MARK_DONE",
            "raw_message":"后台跑这个：apt-get update 2>&1 | head -20; echo JOB_MARK_DONE",
            "font":0,"time":int(time.time()),"self_id":10001,
            "sender":{"user_id":USER_ID,"nickname":"测试用户"},
        }))
        log("sent job request")
        try:
            await asyncio.wait_for(done.wait(), timeout=120)
        except asyncio.TimeoutError:
            log("timeout waiting bot")
        lt.cancel()
        await asyncio.sleep(3)

    # check both logs
    for f in ["ea52de0c-51b7-4b49-a43d-985ed2e09579.log", "ea52de0c-51b7-4b49-a43d-985ed2e09579.jobs.log"]:
        r = subprocess.run(
            ["docker","exec","termman-backend-1","sh","-c",
             f"wc -c /app/backend/app/services/log/{f} /app/.runtime/item_logs/{f} 2>/dev/null; echo ---; tail -c 400 /app/backend/app/services/log/{f} 2>/dev/null || tail -c 400 /app/.runtime/item_logs/{f} 2>/dev/null"],
            capture_output=True, text=True)
        log(f"--- {f} ---")
        print(r.stdout[-600:] if r.stdout else "(missing)")

asyncio.run(main())
