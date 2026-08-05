"""Test plan lifecycle via WEB chat entry: create -> progress -> auto-clear."""
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

# Send web chat in background thread (turn may run long with background jobs)
done = {"flag": False}

def send_web():
    msg = "帮我做两件事：1.后台跑 sleep 5 && echo WEB_STEP1 2.后台跑 sleep 5 && echo WEB_STEP2，按顺序来，都跑完告诉我"
    log(f"web chat: {msg[:50]}...")
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
            json={"message": msg, "history": []},
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=300, stream=True)
        for line in r.iter_lines():
            if line and line.startswith(b"data: "):
                try:
                    p = json.loads(line[6:])
                    if p.get("type") == "agent_response":
                        log(f"  WEB-REPLY: {p.get('content','')[:150]}")
                    elif p.get("type") == "plan_updated":
                        log(f"  [plan_updated event] {json.dumps(p.get('plan',''),ensure_ascii=False)[:200]}")
                except:
                    pass
    except Exception as e:
        log(f"  web error: {e}")
    finally:
        done["flag"] = True

t = threading.Thread(target=send_web, daemon=True)
t.start()

# Monitor plan
plan_seen = False
plan_cleared = False
for i in range(40):  # up to 200s
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

log("=" * 45)
if plan_seen and plan_cleared:
    log("PASS: web plan created -> progressed -> auto-cleared")
elif plan_seen:
    log("FAIL: plan created but never cleared")
else:
    log("FAIL: no plan created")
log(f"web turn done flag: {done['flag']}")
