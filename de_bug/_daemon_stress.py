import requests, json, sys, io, time, subprocess, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Ensure terminal is running
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
print(f"Terminal start: {r.status_code} {r.text[:100]}")
time.sleep(2)

# Find the PTY pid
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "ps -eo pid,tty,cmd | grep pts | grep -v grep"],
    capture_output=True, text=True)
print(f"PTY processes:\n{result.stdout}")

# Get the shell PID
lines = [l for l in result.stdout.strip().split('\n') if 'pts' in l and '/bin/sh' in l]
if lines:
    pid = lines[0].split()[0]
    print(f"Shell PID: {pid}")
else:
    print("No shell found!")
    sys.exit(1)

# TEST 1: Flood output - 1000 lines rapidly
print("\n=== TEST 1: Flood 1000 lines ===")
subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    f"echo 'for i in $(seq 1 1000); do echo flood_line_$i; done' > /proc/{pid}/fd/0"],
    capture_output=True, text=True)
time.sleep(5)

# Check if terminal is still responsive
subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    f"echo 'echo ALIVE_CHECK_1' > /proc/{pid}/fd/0"],
    capture_output=True, text=True)
time.sleep(2)

# Read terminal log tail
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    f"tail -5 /app/log/{ITEM}.log 2>/dev/null || echo 'no log'"],
    capture_output=True, text=True)
print(f"Log tail:\n{result.stdout}")

# TEST 2: Run a process that produces continuous output for 10s
print("\n=== TEST 2: Continuous output (yes | head -10000) ===")
subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    f"echo 'yes continuous_test | head -10000' > /proc/{pid}/fd/0"],
    capture_output=True, text=True)
time.sleep(8)

# Check responsiveness again
subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    f"echo 'echo ALIVE_CHECK_2' > /proc/{pid}/fd/0"],
    capture_output=True, text=True)
time.sleep(2)

result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    f"tail -3 /app/log/{ITEM}.log 2>/dev/null"],
    capture_output=True, text=True)
print(f"Log tail after continuous:\n{result.stdout}")

# TEST 3: Kill the shell child and see if daemon detects
print("\n=== TEST 3: Check daemon thread status ===")
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "ps -eLo pid,tid,stat,comm | grep -E 'python|PID' | head -20"],
    capture_output=True, text=True)
print(f"Daemon threads:\n{result.stdout}")

# TEST 4: Check if _read_output thread is alive by checking daemon logs
result = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
    "tail -20 /app/daemon.log 2>/dev/null || echo 'no daemon.log'"],
    capture_output=True, text=True)
print(f"Daemon log:\n{result.stdout[:500]}")

print("\n=== TEST 5: Session check ===")
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=3&offset=0", headers=h)
data = r.json()
total = data.get("total", 0)
print(f"Session: {total}")
msgs = data if isinstance(data, list) else data.get("messages", data.get("history", []))
for m in msgs[:3]:
    print(f"  {m.get('role')}: {str(m.get('content',''))[:150]}")