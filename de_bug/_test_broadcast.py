"""Test: broadcast to multiple QQ targets (private + group)."""
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
GROUP_ID = 770362397

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def _headers():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
        data={"username": "admin@example.com", "password": "changethis"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def get_plan():
    try:
        r = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=_headers(), timeout=15)
        return r.json().get("plan", [])
    except:
        return []

def send_private(ws, text):
    event = {
        "post_type": "message", "message_type": "private", "sub_type": "friend",
        "message_id": int(time.time() * 1000) % 2**31,
        "user_id": USER_ID, "message": text, "raw_message": text, "font": 0,
        "time": int(time.time()), "self_id": 10001,
        "sender": {"user_id": USER_ID, "nickname": "测试用户"},
    }
    return ws.send(json.dumps(event))

async def main():
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        log("WS connected")

        sends = []  # (action, target, text)
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                action = data.get("action", "")
                if "send" in action:
                    params = data.get("params", {})
                    m = params.get("message", "")
                    msg_text = ("".join(seg.get("data",{}).get("text","")
                                for seg in m if isinstance(seg,dict))
                                if isinstance(m, list) else str(m))
                    target = params.get("group_id") or params.get("user_id") or "?"
                    kind = "group" if params.get("group_id") else "private"
                    log(f"  BOT->{kind}:{target}: {msg_text[:180]}")
                    sends.append((kind, str(target), msg_text))
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        # 任务1: 明确要求双发
        log("=" * 55)
        log("BROADCAST TEST 1: 私聊+群双发")
        log("=" * 55)
        await send_private(ws, f"帮我跑 echo BROADCAST_OK，然后把结果同时发到私聊 {USER_ID} 和群 {GROUP_ID}")

        t0 = time.time()
        while time.time() - t0 < 150:
            await asyncio.sleep(5)
            kinds = {k for k, _, _ in sends}
            if "private" in kinds and "group" in kinds:
                log("both targets received!")
                break
        await asyncio.sleep(10)

        plan = get_plan()
        private_hits = [s for s in sends if s[0] == "private"]
        group_hits = [s for s in sends if s[0] == "group"]
        log(f"private msgs: {len(private_hits)} | group msgs: {len(group_hits)}")
        log(f"plan leftover: {[(s.get('status'), s.get('step','')[:25]) for s in plan] if plan else '(none)'}")

        # 任务2: 群广播 only（web 风格指令）
        log("=" * 55)
        log("BROADCAST TEST 2: 只发群")
        log("=" * 55)
        sends.clear()
        await send_private(ws, f"往群 {GROUP_ID} 发一条消息：'群内广播测试'，发完在私聊告诉我发了没")

        t0 = time.time()
        while time.time() - t0 < 120:
            await asyncio.sleep(5)
            kinds = {k for k, _, _ in sends}
            if "group" in kinds and "private" in kinds:
                break
        await asyncio.sleep(5)

        group_hits2 = [s for s in sends if s[0] == "group"]
        private_hits2 = [s for s in sends if s[0] == "private"]
        log(f"group msgs: {len(group_hits2)} | private confirm: {len(private_hits2)}")

        lt.cancel()
        log("=" * 55)
        log("RESULTS")
        log("=" * 55)
        t1 = len(private_hits) > 0 and len(group_hits) > 0
        t2 = len(group_hits2) > 0
        log(f"  双发(私聊+群): {'PASS' if t1 else 'FAIL'}")
        log(f"  指定群发送: {'PASS' if t2 else 'FAIL'}")

asyncio.run(main())
