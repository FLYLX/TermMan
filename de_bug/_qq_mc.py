import requests, json, sys, io, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

baseline = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h).json().get("total", 0)
print(f"Baseline: {baseline}")

# QQ dispatch
payload = {
    "sender_key": "private_2537134688",
    "text": "用Java21帮我启动MC服务器1.20.1，server.jar在items/5目录下，启动完了告诉我",
    "reply_target": {
        "target_type": "private",
        "target_id": "2537134688",
        "metadata": {
            "sender_name": "FLY",
            "sender_id": "2537134688",
            "conversation_type": "private"
        }
    }
}
data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request(
    f"{BASE}/api/v1/robots/{ROBOT}/dispatch",
    data=data,
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "X-TermPaws-Bridge-Token": SECRET,
    },
    method="POST"
)
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode('utf-8'))
print(f"QQ dispatch: {json.dumps(result, ensure_ascii=False)[:200]}")

# Monitor
last_total = baseline
for check in range(8):
    time.sleep(20)
    
    r2 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
    wf = r2.json()
    wf_info = ""
    for w in wf.get("workflows", []):
        steps = " | ".join([f"{s.get('title','')[:25]}:{s.get('status','')}" for s in w.get("steps", [])])
        wf_info = f"WF={w.get('status')} [{steps}]"
    
    r3 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h)
    total = r3.json().get("total", 0)
    delta = total - last_total
    last_total = total
    
    # Check for QQ reply attempts in recent messages
    r4 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=2&offset=0", headers=h)
    d4 = r4.json()
    msgs = d4 if isinstance(d4, list) else d4.get("messages", d4.get("history", []))
    last_msg = ""
    has_qq_reply = False
    for m in msgs[:2]:
        c = str(m.get("content", ""))
        if "mcp_robot_send_message" in c or "QQ" in c or "robot" in c.lower():
            has_qq_reply = True
        if m.get("role") == "assistant" and len(c) > 20:
            last_msg = c[:150]
    
    print(f"[{(check+1)*20}s] session={total}(+{delta}) qq_reply={has_qq_reply} {wf_info}")
    if last_msg:
        print(f"  last: {last_msg}")
    
    # Check java process
    import subprocess
    jr = subprocess.run(["docker", "exec", "TermPaws-daemon-1", "sh", "-c",
        "ps aux | grep 'server.jar' | grep -v grep | wc -l"],
        capture_output=True, text=True)
    mc = jr.stdout.strip()
    if mc == "1":
        print(">>> MC SERVER RUNNING <<<")

print(f"\n=== Final messages ===")
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
d5 = r5.json()
total = d5.get("total", 0)
print(f"Session: {total} (was {baseline}, +{total-baseline})")
msgs = d5 if isinstance(d5, list) else d5.get("messages", d5.get("history", []))
for i, m in enumerate(msgs):
    print(f"[{i}] {m.get('role')}: {str(m.get('content',''))[:250]}")
    print()