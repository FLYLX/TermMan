import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Start terminal
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
print(f"Terminal: {r.status_code} {r.text[:80]}")
time.sleep(3)

# Get shell PID
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "ps -eo pid,tty,cmd | grep pts | grep '/bin/sh' | grep -v grep | awk '{print $1}'"],
    capture_output=True, text=True)
pid = result.stdout.strip().split('\n')[0] if result.stdout.strip() else None
print(f"Shell PID: {pid}")
if not pid:
    print("FATAL: no shell"); sys.exit(1)

def daemon_mem():
    r2 = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
        "cat /proc/1/status | grep -E 'VmRSS|Threads'"],
        capture_output=True, text=True)
    return r2.stdout.strip().replace('\n', ' | ')

def write_term(cmd):
    subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
        f"echo '{cmd}' > /proc/{pid}/fd/0"], capture_output=True, text=True)

# === TEST 1: Flood 2000 lines ===
print(f"\n=== TEST 1: Flood 2000 lines === mem={daemon_mem()}")
write_term("for i in $(seq 1 2000); do echo flood_$i; done")
time.sleep(8)
write_term("echo FLOOD_DONE")
time.sleep(3)
print(f"After flood: mem={daemon_mem()}")

# === TEST 2: Continuous output ===
print(f"\n=== TEST 2: yes | head -50000 ===")
write_term("yes stress_test | head -50000")
time.sleep(10)
write_term("echo CONT_DONE")
time.sleep(3)
print(f"After continuous: mem={daemon_mem()}")

# === TEST 3: MC server ===
print(f"\n=== TEST 3: MC server start ===")
mc_dir = "/app/src/workdir/909edfa7-714c-498e-9907-7fc31c07c143/ea52de0c-51b7-4b49-a43d-985ed2e09579/app/src/workdir/ed04396a-a605-46f4-9e07-8fcdf0edfe7c/ea52de0c-51b7-4b49-a43d-985ed2e09579/app/items/5"
write_term(f"cd {mc_dir} && /opt/amazon-corretto-25.0.4.7.1-linux-x64/bin/java -Xmx512M -jar server.jar nogui")

for check in range(4):
    time.sleep(20)
    mc_r = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
        "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
        capture_output=True, text=True)
    mc = mc_r.stdout.strip()
    print(f"  [{(check+1)*20}s] MC={mc} | {daemon_mem()}")

# Send list command to MC console
write_term("list")
time.sleep(3)

# === TEST 4: Stop MC ===
print(f"\n=== TEST 4: Stop MC ===")
write_term("stop")
time.sleep(8)
mc_r = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
    capture_output=True, text=True)
print(f"MC after stop: {mc_r.stdout.strip()}")

# === TEST 5: Terminal still responsive? ===
print(f"\n=== TEST 5: Responsiveness ===")
write_term("echo FINAL_ALIVE_CHECK")
time.sleep(3)
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    f"tail -5 /app/log/{ITEM}.log 2>/dev/null"],
    capture_output=True, text=True)
print(f"Log tail:\n{result.stdout}")
print(f"Final mem: {daemon_mem()}")

# Session check
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=2&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
print(f"Session: {total}")
for m in msgs[:2]:
    print(f"  {m.get('role')}: {str(m.get('content',''))[:150]}")