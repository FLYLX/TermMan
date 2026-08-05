"""Complex scenario tests with token usage tracking."""
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

def get_plan():
    try:
        r = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=_headers(), timeout=15)
        return r.json().get("plan", [])
    except:
        return []

def get_total_tokens():
    """Sum total tokens across all tasks."""
    try:
        r = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage/by-task?limit=100",
                         headers=_headers(), timeout=15)
        tasks = r.json().get("tasks", [])
        return sum(t.get("total_tokens", 0) for t in tasks), len(tasks)
    except Exception as e:
        return -1, -1

def send_qq_msg(ws, text):
    event = {
        "post_type": "message", "message_type": "private", "sub_type": "friend",
        "message_id": int(time.time() * 1000) % 2**31,
        "user_id": USER_ID, "message": text, "raw_message": text, "font": 0,
        "time": int(time.time()), "self_id": 10001,
        "sender": {"user_id": USER_ID, "nickname": "测试用户"},
    }
    return ws.send(json.dumps(event))

async def wait_bot_done(received, baseline, timeout_s=180, quiet_s=25):
    """Wait until bot stops sending messages for quiet_s seconds."""
    start = time.time()
    while time.time() - start < timeout_s:
        await asyncio.sleep(5)
        if len(received) > baseline:
            # check quiet period: no new message in last quiet_s
            await asyncio.sleep(quiet_s)
            if len(received) > baseline:
                # still getting messages, keep waiting
                baseline = len(received)
                continue
            return True
    return False

async def run_scenario(ws, received, name, message, timeout_s=180):
    log("=" * 55)
    log(f"SCENARIO: {name}")
    log("=" * 55)
    tok_before, _ = get_total_tokens()
    baseline = len(received)
    log(f"send: {message[:60]}")
    await send_qq_msg(ws, message)
    t0 = time.time()
    await wait_bot_done(received, baseline, timeout_s=timeout_s)
    elapsed = time.time() - t0
    tok_after, _ = get_total_tokens()
    delta = tok_after - tok_before if tok_before >= 0 and tok_after >= 0 else -1
    new_msgs = received[baseline:]
    log(f"done in {elapsed:.0f}s | tokens: {delta} | bot msgs: {len(new_msgs)}")
    for m in new_msgs[-3:]:
        log(f"  bot: {m[:140]}")
    plan = get_plan()
    if plan:
        log(f"  leftover plan: {[(s.get('status'), s.get('step','')[:25]) for s in plan]}")
    return {"name": name, "elapsed": elapsed, "tokens": delta, "msgs": len(new_msgs)}

async def main():
    import websockets
    async with websockets.connect(WS_URL, additional_headers=HEADERS,
                                  ping_interval=20, ping_timeout=10) as ws:
        log("WS connected")
        received = []
        async def listener():
            async for raw in ws:
                data = json.loads(raw)
                if "send" in data.get("action", ""):
                    params = data.get("params", {})
                    m = params.get("message", "")
                    msg_text = ("".join(seg.get("data",{}).get("text","")
                                for seg in m if isinstance(seg,dict))
                                if isinstance(m, list) else str(m))
                    log(f"  BOT: {msg_text[:200]}")
                    received.append(msg_text)
                    await ws.send(json.dumps({"status":"ok","retcode":0,
                        "data":{"message_id":int(time.time())},"echo":data.get("echo","")}))
        lt = asyncio.create_task(listener())

        results = []

        # S1: 多步任务 + 验证
        results.append(await run_scenario(ws, received,
            "S1 多步安装+验证",
            "帮我安装 fortune 这个命令，装完跑一下确认能用"))

        # S2: 错误恢复（命令不存在 → 换方法）
        results.append(await run_scenario(ws, received,
            "S2 错误恢复",
            "帮我跑一下 nyancat，如果没有就装一个再跑"))

        # S3: 并行后台 job
        results.append(await run_scenario(ws, received,
            "S3 并行job",
            "同时后台跑两个任务：sleep 20 && echo A 和 sleep 25 && echo B，都结束告诉我"))

        # S4: 长任务中途取消
        log("=" * 55); log("SCENARIO: S4 长任务取消"); log("=" * 55)
        tok_before, _ = get_total_tokens()
        baseline = len(received)
        await send_qq_msg(ws, "后台跑 sleep 300 && echo NEVER")
        await asyncio.sleep(20)
        await send_qq_msg(ws, "取消任务")
        t0 = time.time()
        await wait_bot_done(received, baseline, timeout_s=90)
        tok_after, _ = get_total_tokens()
        plan = get_plan()
        log(f"cancel done in {time.time()-t0:.0f}s | tokens: {tok_after-tok_before} | plan leftover: {plan}")
        results.append({"name": "S4 取消", "elapsed": time.time()-t0,
                        "tokens": tok_after-tok_before, "msgs": len(received)-baseline})

        # S5: 上下文追问（依赖历史）
        results.append(await run_scenario(ws, received,
            "S5 上下文追问",
            "刚才那些后台任务都跑完了吗", timeout_s=90))

        lt.cancel()
        log("\n" + "=" * 55)
        log("TOKEN & TIME SUMMARY")
        log("=" * 55)
        total = 0
        for r in results:
            log(f"  {r['name']:<14} {r['elapsed']:>5.0f}s  {r['tokens']:>8} tokens  {r['msgs']} msgs")
            total += max(r["tokens"], 0)
        log(f"  {'TOTAL':<14} {'':>5}  {total:>8} tokens")

asyncio.run(main())
