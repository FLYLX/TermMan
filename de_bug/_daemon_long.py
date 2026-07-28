import requests, json, sys, io, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

result = subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
    "ps -eo pid,tty,cmd | grep pts | grep -v grep"],
    capture_output=True, text=True)
lines = [l for l in result.stdout.strip().split('\n') if 'pts' in l and '/bin/sh' in l]
pid = lines[0].split()[0] if lines else None
print(f"Shell PID: {pid}")

mc_dir = "/app/src/workdir/909edfa7-714c-498e-9907-7fc31c07c143/ea52de0c-51b7-4b49-a43d-985ed2e09579/app/src/workdir/ed04396a-a605-46f4-9e07-8fcdf0edfe7c/ea52de0c-51b7-4b49-a43d-985ed2e09579/app/items/5"
cmd = f"cd {mc_dir} && /opt/amazon-corretto-25.0.4.7.1-linux-x64/bin/java -Xmx512M -jar server.jar nogui"
print(f"Starting MC server...")
subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
    f"echo '{cmd}' > /proc/{pid}/fd/0"],
    capture_output=True, text=True)

print("\nMonitoring daemon health every 20s for 2 minutes...")
for check in range(6):
    time.sleep(20)
    result = subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
        "cat /proc/1/status | grep -E 'VmRSS|VmSize|Threads'"],
        capture_output=True, text=True)
    mem = result.stdout.strip().replace('\n', ' | ')
    result = subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
        "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
        capture_output=True, text=True)
    mc = result.stdout.strip()
    subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
        f"echo 'list' > /proc/{pid}/fd/0"],
        capture_output=True, text=True)
    result = subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
        f"wc -c /app/log/{ITEM}.log 2>/dev/null | awk '{{print $1}}'"],
        capture_output=True, text=True)
    logsize = result.stdout.strip()
    r2 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
    total = r2.json().get("total", 0)
    print(f"[{(check+1)*20}s] MC={mc} | {mem} | log={logsize}B | session={total}")

print("\nStopping MC server...")
subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
    f"echo 'stop' > /proc/{pid}/fd/0"],
    capture_output=True, text=True)
time.sleep(5)
result = subprocess.run(["docker", "exec", "termman-daemon-1", "sh", "-c",
    "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
    capture_output=True, text=True)
print(f"MC after stop: {result.stdout.strip()}")
result = subprocess.run(["docker", "exec", "termman-daemon-1", "python", "-c",
    "print('daemon alive')"],
    capture_output=True, text=True)
print(f"Daemon: {result.stdout.strip()}")