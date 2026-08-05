"""Token usage probe: QQ casual chat vs web chat, per-turn token cost."""
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

def _headers():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
        data={"username": "admin@example.com", "password": "changethis"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def token_snapshot():
    r = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage/by-task?limit=100",
                     headers=_headers(), timeout=15)
    return {t["reply_ticket_id"]: t for t in r.json().get("tasks", [])}

def total_tokens(snap):
    return sum(t.get("total_tokens", 0) for t in snap.values())

async def qq_chat(text):
    """Send one QQ message, wait for reply, return elapsed."""
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        got = asyncio.Event()
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    got.set()
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())
        await ws.send(json.dumps({
            "post_type":"message","message_type":"private","sub_type":"friend",
            "message_id":int(time.time()*1000)%2**31,
            "user_id":USER_ID,"message":text,"raw_message":text,"font":0,
            "time":int(time.time()),"self_id":10001,
            "sender":{"user_id":USER_ID,"nickname":"测试用户"},
        }))
        t0 = time.time()
        try:
            await asyncio.wait_for(got.wait(), timeout=90)
        except asyncio.TimeoutError:
            pass
        lt.cancel()
        return time.time() - t0

def web_chat(text):
    t0 = time.time()
    r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
        json={"message": text, "history": []},
        headers={**_headers(), "Content-Type": "application/json"},
        timeout=120, stream=True)
    reply = ""
    for line in r.iter_lines():
        if line and line.startswith(b"data: "):
            try:
                p = json.loads(line[6:])
                if p.get("type") == "agent_response":
                    reply += p.get("content", "")
            except:
                pass
    return time.time() - t0, reply

async def main():
    before = token_snapshot()
    before_total = total_tokens(before)
    log(f"snapshot before: {before_total} tokens across {len(before)} tickets")

    # QQ casual chats
    log("--- QQ casual chat ---")
    qq_msgs = ["在吗", "1+1等于几", "今天天气怎么样"]
    for m in qq_msgs:
        t = await qq_chat(m)
        log(f"  QQ '{m}' answered in {t:.0f}s")

    mid = token_snapshot()
    qq_new = {k: v for k, v in mid.items() if k not in before}
    qq_tokens = sum(t.get("total_tokens", 0) for t in qq_new.values())
    log(f"QQ: {len(qq_new)} tickets, {qq_tokens} tokens total")

    # Web casual chats
    log("--- web chat ---")
    web_msgs = ["在吗", "1+1等于几", "今天天气怎么样"]
    for m in web_msgs:
        t, reply = web_chat(m)
        log(f"  web '{m}' answered in {t:.0f}s: {reply[:60]}")

    after = token_snapshot()
    web_new = {k: v for k, v in after.items() if k not in mid}
    web_tokens = sum(t.get("total_tokens", 0) for t in web_new.values())
    log(f"web: {len(web_new)} tickets, {web_tokens} tokens total")

    log("=" * 50)
    log("PER-TICKET DETAIL (new tickets)")
    for k, v in {**qq_new, **web_new}.items():
        src = v.get("source_type") or "?"
        log(f"  [{src:>4}] prompt={v.get('prompt_tokens',0):>6} completion={v.get('completion_tokens',0):>5} total={v.get('total_tokens',0):>6} turns={v.get('turns',0)} req={str(v.get('request_message',''))[:30]}")

    if qq_new:
        avg_qq = qq_tokens // max(len(qq_new),1)
        log(f"QQ avg per msg: ~{avg_qq} tokens")
    if web_new:
        avg_web = web_tokens // max(len(web_new),1)
        log(f"web avg per msg: ~{avg_web} tokens")

asyncio.run(main())
