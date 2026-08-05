"""Reproduce: web turn starts bg job, watch what happens after job completes."""
import json, time, requests, threading

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def _headers():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
        data={"username": "admin@example.com", "password": "changethis"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

done = {"flag": False, "at": None}

def send_web():
    msg = "后台跑 sleep 8 && echo CALLBACK_TEST，跑完告诉我结果"
    log(f"web chat: {msg}")
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
            json={"message": msg, "history": []},
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=120, stream=True)
        for line in r.iter_lines():
            if line and line.startswith(b"data: "):
                try:
                    p = json.loads(line[6:])
                    t = p.get("type", "")
                    if t == "agent_response":
                        log(f"  WEB-REPLY: {p.get('content','')[:150]}")
                    elif p.get("done"):
                        log("  stream done")
                except:
                    pass
    except Exception as e:
        log(f"  web error: {e}")
    finally:
        done["flag"] = True
        done["at"] = time.strftime('%H:%M:%S')
        log(f"  turn ended at {done['at']}")

t = threading.Thread(target=send_web, daemon=True)
t.start()

# Watch backend logs for 90s after turn ends
time.sleep(30)
log("--- tailing backend logs ---")
import subprocess
proc = subprocess.Popen(
    ["docker", "logs", "termman-backend-1", "--since", "2m", "-f"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
start = time.time()
while time.time() - start < 75:
    line = proc.stdout.readline()
    if not line:
        time.sleep(0.2)
        continue
    if any(k in line for k in ["AgentSession", "run_job result", "CALLBACK", "LiteLLM", "flush", "Queued", "consumer", "lease", "coordinator"]):
        print(line[:220], flush=True)
proc.kill()
log("done")
