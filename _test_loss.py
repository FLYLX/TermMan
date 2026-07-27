import requests, time, sys, io, subprocess, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
h = {"Authorization": f"Bearer {r.json()['access_token']}"}
requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
time.sleep(3)

# Phase 1: Continuous terminal output (simulate MC logs)
print("=== Phase 1: Continuous terminal output ===")
def write_lines(start, count, delay=0.4):
    for i in range(count):
        subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
            f"PID=$(ps -eo pid,tty | grep pts | head -1 | awk '{{print $1}}'); echo '[Server] Player_{start+i} joined the game' > /proc/$PID/fd/0"],
            capture_output=True)
        time.sleep(delay)

t1 = threading.Thread(target=write_lines, args=(1, 8, 0.4), daemon=True)
t1.start()

# Phase 2: Send chat while terminal is active
time.sleep(1.5)
print("Sending chat during terminal output...")
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "服务器有人在线吗", "history": []}, headers=h)
print(f"Chat: {r.status_code} content={str(r.json().get('content',''))[:100]}")

# Wait for everything to settle
t1.join(timeout=10)
time.sleep(15)

# Check results
print("\n=== Results ===")
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=10&offset=0", headers=h)
msgs = r.json() if isinstance(r.json(), list) else r.json().get("messages", [])
terminal_msgs = [m for m in msgs if m.get("role") == "terminal"]
assistant_msgs = [m for m in msgs if m.get("role") == "assistant" and str(m.get("content","")).strip()]

print(f"Terminal messages in session: {len(terminal_msgs)}")
print(f"Assistant replies: {len(assistant_msgs)}")

# Check if agent saw the Player_* messages
all_content = " ".join(str(m.get("content","")) for m in msgs)
players_seen = [f"Player_{i}" for i in range(1, 9) if f"Player_{i}" in all_content]
print(f"Players seen by agent: {players_seen}")

# Last assistant message
for m in reversed(msgs):
    if m.get("role") == "assistant" and str(m.get("content","")).strip():
        print(f"\nLast reply: {str(m.get('content',''))[:250]}")
        break

# Check not stuck
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
active = [wf for wf in r.json().get("workflows", []) if wf['status'] not in ('completed','cancelled','failed')]
print(f"\nActive workflows: {len(active)}")
print("*** OK: Not stuck ***" if len(active) == 0 else f"*** CHECK: {len(active)} active ***")
