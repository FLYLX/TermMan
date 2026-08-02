import requests, json, time, threading, sys

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

msg = "帮我同时做两件事：1.安装Python 3.6  2.安装Java 17。两件事并行做，装完都验证一下"
print(f"[0s] Sending: {msg}", flush=True)

done = {"flag": False, "content": "", "error": ""}

def send_msg():
    try:
        r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
            json={"message": msg, "history": []},
            headers=h, timeout=600, stream=True)
        chunks = []
        for line in r2.iter_lines():
            if line:
                line = line.decode("utf-8", errors="replace")
                if line.startswith("data: "):
                    try:
                        payload = json.loads(line[6:])
                        if payload.get("type") == "agent_response":
                            chunks.append(payload.get("content", ""))
                        elif payload.get("type") == "agent_action":
                            print(f"  [action] {payload.get('content','')[:100]}", flush=True)
                        elif payload.get("type") == "agent_tool_result":
                            print(f"  [tool_result] {payload.get('content','')[:100]}", flush=True)
                        elif payload.get("type") == "plan_updated":
                            print(f"  [PLAN UPDATED] {json.dumps(payload.get('plan',''),ensure_ascii=False)[:200]}", flush=True)
                        elif payload.get("done"):
                            pass
                    except:
                        pass
        done["content"] = "".join(chunks)
    except Exception as e:
        done["error"] = str(e)[:300]
    finally:
        done["flag"] = True

t = threading.Thread(target=send_msg, daemon=True)
t.start()

# Poll plan for 8 minutes
for i in range(48):
    time.sleep(10)
    el = (i+1)*10
    if done["flag"]:
        if done["error"]:
            print(f"\n[{el}s] CHAT ERROR: {done['error']}", flush=True)
        else:
            print(f"\n[{el}s] CHAT DONE: {done['content'][:300]}", flush=True)
        break
    try:
        r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10)
        if r3.status_code == 200:
            plan = r3.json().get("plan", [])
            if plan:
                steps = " | ".join(f"{j+1}.[{s.get('status','?')}] {s.get('step','?')[:25]}" for j,s in enumerate(plan))
                print(f"[{el}s] plan({len(plan)}): {steps}", flush=True)
            else:
                print(f"[{el}s] no plan", flush=True)
    except Exception as e:
        print(f"[{el}s] plan err: {e}", flush=True)

if not done["flag"]:
    t.join(timeout=30)
    if done["flag"]:
        print(f"\nFINAL: {done.get('content','')[:400] or done.get('error','')}", flush=True)
    else:
        print("\nFINAL: chat still running (timeout)", flush=True)

print("\n=== Final plan ===", flush=True)
try:
    r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10)
    plan = r5.json().get("plan", [])
    if plan:
        for j,s in enumerate(plan):
            print(f"  {j+1}. [{s.get('status','?')}] {s.get('step','?')}", flush=True)
    else:
        print("  (no plan)", flush=True)
except Exception as e:
    print(f"  err: {e}", flush=True)
