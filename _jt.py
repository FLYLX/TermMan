# -*- coding: utf-8 -*-
import requests, threading, time, json

BASE = "http://localhost:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

resp = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"},
    headers={"Content-Type": "application/x-www-form-urlencoded"})
token = resp.json()["access_token"]
hdrs = {"Authorization": f"Bearer {token}"}

events = []
stop = threading.Event()

def listen():
    try:
        r = requests.get(f"{BASE}/api/v1/chat/{ITEM}/agent-events",
            headers={**hdrs, "Accept": "text/event-stream"}, stream=True, timeout=300)
        for line in r.iter_lines(decode_unicode=True):
            if stop.is_set(): break
            if line and line.startswith("data: "):
                d = json.loads(line[6:])
                events.append(d)
                t = d.get("type","?")
                c = str(d.get("content",""))[:100]
                ts = time.strftime("%H:%M:%S")
                print(f"  {ts} [{t}] {c}", flush=True)
    except Exception as e:
        if not stop.is_set(): print(f"SSE error: {e}")

t = threading.Thread(target=listen, daemon=True)
t.start()
time.sleep(2)

# First uninstall Java
msg = "uninstall temurin-17-jdk and any java packages, then verify java -version shows not found"
print(f">>> {msg}")
resp = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    headers={**hdrs, "Content-Type": "application/json"},
    json={"message": msg, "history": []})

# Wait for uninstall to complete
for i in range(36):
    time.sleep(5)
    types = [e.get("type") for e in events]
    if types.count("agent_response") >= 1:
        time.sleep(3)
        break
    if i % 6 == 5:
        print(f"  ... waiting ({(i+1)*5}s, {len(events)} events)", flush=True)

print(f"\n=== UNINSTALL: {len(events)} events ===")
for e in events:
    if e.get("type") == "agent_response":
        print(f"  >> {e.get('content','')[:150]}")

# Now install Java again
events.clear()
time.sleep(2)
msg2 = "install openjdk-17-jdk-headless, verify with java -version"
print(f"\n>>> {msg2}")
resp = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    headers={**hdrs, "Content-Type": "application/json"},
    json={"message": msg2, "history": []})

for i in range(48):
    time.sleep(5)
    types = [e.get("type") for e in events]
    if "agent_response" in types:
        time.sleep(3)
        break
    if i % 6 == 5:
        print(f"  ... waiting ({(i+1)*5}s, {len(events)} events)", flush=True)

stop.set()
time.sleep(1)

types = [e.get("type") for e in events]
resp_count = types.count("agent_response")
print(f"\n=== INSTALL: {len(events)} events | agent_response count: {resp_count} ===")
for e in events:
    if e.get("type") in ("agent_response", "agent_warning", "agent_error"):
        print(f"  [{e['type']}] {e.get('content','')[:200]}")
