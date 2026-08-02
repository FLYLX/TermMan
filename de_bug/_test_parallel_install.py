import requests, json, time, threading

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

# Login
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Send message in background thread
msg = "帮我同时做两件事：1.安装Python 3.6  2.安装Java 17。两件事并行做，装完都验证一下"
print(f"[0s] Sending: {msg}")

result_holder = {"done": False, "response": None, "error": None}

def send_message():
    try:
        r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
            json={"message": msg, "history": []},
            headers=h, timeout=600)
        result_holder["response"] = r2.json()
    except Exception as e:
        result_holder["error"] = str(e)
    finally:
        result_holder["done"] = True

t = threading.Thread(target=send_message, daemon=True)
t.start()

# Poll plan status for up to 8 minutes
print("=== Monitoring plan status ===")
for i in range(48):
    time.sleep(10)
    elapsed = (i+1) * 10

    # Check if chat response arrived
    if result_holder["done"]:
        if result_holder["error"]:
            print(f"[{elapsed}s] CHAT ERROR: {result_holder['error'][:200]}")
        elif result_holder["response"]:
            content = result_holder["response"].get("content", "")
            print(f"[{elapsed}s] CHAT RESPONSE: {content[:300]}")
        break

    # Check plan
    try:
        r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10)
        if r3.status_code == 200:
            plan_data = r3.json()
            plan = plan_data.get("plan", [])
            if plan:
                steps_str = " | ".join(f"{j+1}.[{s.get('status','?')}] {s.get('step','?')[:25]}" for j,s in enumerate(plan))
                print(f"[{elapsed}s] plan({len(plan)}): {steps_str}")
            else:
                print(f"[{elapsed}s] no plan")
    except Exception as e:
        print(f"[{elapsed}s] plan err: {e}")

    # Check tickets
    try:
        r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/reply-tickets", headers=h, timeout=10)
        if r4.status_code == 200:
            tickets = r4.json() if isinstance(r4.json(), list) else r4.json().get("tickets", [])
            active = [t for t in tickets if t.get("status") in ("pending","running","sending")]
            for tk in active[:2]:
                print(f"  ticket {tk.get('ticket_id','')[:8]}: status={tk.get('status')} req={tk.get('request_message','')[:40]}")
    except:
        pass

# If chat still not done, wait a bit more
if not result_holder["done"]:
    t.join(timeout=60)
    if result_holder["done"]:
        if result_holder["response"]:
            print(f"\nFINAL: {result_holder['response'].get('content','')[:500]}")
        elif result_holder["error"]:
            print(f"\nFINAL ERROR: {result_holder['error'][:200]}")
    else:
        print("\nFINAL: chat still running (agent took too long)")

# Final plan check
print("\n=== Final plan ===")
try:
    r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10)
    if r5.status_code == 200:
        plan = r5.json().get("plan", [])
        if plan:
            for j, step in enumerate(plan):
                print(f"  {j+1}. [{step.get('status','?')}] {step.get('step','?')}")
        else:
            print("  (no plan - cleared or never created)")
except Exception as e:
    print(f"  error: {e}")
