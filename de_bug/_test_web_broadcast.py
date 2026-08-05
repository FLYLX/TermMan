"""Test: web-originated direct broadcast (no background job)."""
import json, time, requests, threading, asyncio

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

sends = []

async def ws_listener():
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        log("WS listener connected")
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

def run_ws():
    asyncio.run(ws_listener())

t = threading.Thread(target=run_ws, daemon=True)
t.start()
time.sleep(3)

msg = f"把消息 'WEB_DIRECT_OK' 发到私聊 {USER_ID} 和群 {GROUP_ID}，两个都要发到，发完告诉我"
log(f"web chat: {msg}")
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": msg, "history": []},
    headers={**_headers(), "Content-Type": "application/json"},
    timeout=240, stream=True)
for line in r.iter_lines():
    if line:
        line = line.decode("utf-8", errors="replace")
        if line.startswith("data: "):
            try:
                p = json.loads(line[6:])
                if p.get("type") == "agent_response":
                    log(f"  WEB-REPLY: {p.get('content','')[:200]}")
            except:
                pass

log("waiting 30s for late sends...")
time.sleep(30)
log("=" * 50)
private_hits = [s for s in sends if s[0] == "private"]
group_hits = [s for s in sends if s[0] == "group"]
log(f"private msgs: {len(private_hits)} | group msgs: {len(group_hits)}")
ok = len(private_hits) > 0 and len(group_hits) > 0
log(f"web direct broadcast: {'PASS' if ok else 'FAIL'}")
