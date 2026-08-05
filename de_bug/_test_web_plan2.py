"""Web plan test: listen on agent-events SSE for plan_updated + follow-up replies."""
import json, time, requests, threading

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

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

stop = threading.Event()

def listen_events():
    """agent-events SSE: plan_updated + chat events broadcast."""
    try:
        r = requests.get(f"{BASE}/api/v1/chat/{ITEM}/agent-events",
                         headers=_headers(), stream=True, timeout=180)
        for line in r.iter_lines():
            if stop.is_set():
                break
            if not line:
                continue
            s = line.decode("utf-8", errors="replace")
            if not s.startswith("data: "):
                continue
            try:
                p = json.loads(s[6:])
            except:
                continue
            t = p.get("type", "")
            if t == "plan_updated":
                log(f"  [SSE plan_updated] {json.dumps(p.get('plan',''),ensure_ascii=False)[:180]}")
            elif t in ("agent_response", "chat_message"):
                log(f"  [SSE {t}] {str(p.get('content',''))[:150]}")
    except Exception as e:
        log(f"  SSE error: {e}")

et = threading.Thread(target=listen_events, daemon=True)
et.start()
time.sleep(2)

def send_web():
    msg = "帮我做三件事：1.后台跑 sleep 5 && echo WEB_A 2.后台跑 sleep 5 && echo WEB_B 3.两个都跑完后读一下终端日志确认两个输出都在，然后汇报。按顺序来"
    log(f"web chat: {msg[:45]}...")
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
            json={"message": msg, "history": []},
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=120, stream=True)
        for line in r.iter_lines():
            if line and line.startswith(b"data: "):
                try:
                    p = json.loads(line[6:])
                    if p.get("type") == "agent_response":
                        log(f"  [turn1 reply] {p.get('content','')[:120]}")
                except:
                    pass
        log("  turn1 stream closed")
    except Exception as e:
        log(f"  web error: {e}")

t = threading.Thread(target=send_web, daemon=True)
t.start()

plan_seen = False
plan_cleared = False
for i in range(30):
    time.sleep(5)
    plan = get_plan()
    el = (i+1)*5
    if plan:
        plan_seen = True
        log(f"  [{el}s] plan: {[(s.get('status'), s.get('step','')[:28]) for s in plan]}")
    else:
        if plan_seen and not plan_cleared:
            log(f"  [{el}s] plan AUTO-CLEARED")
            plan_cleared = True
            break
        elif not plan_seen:
            log(f"  [{el}s] waiting...")

stop.set()
log("=" * 45)
status = "PASS" if (plan_seen and plan_cleared) else ("FAIL: no plan" if not plan_seen else "FAIL: not cleared")
log(status)
