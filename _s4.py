# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

# TEST 1: Web chat simple
print("=== S4-1: Web chat simple ===")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={
    "message": "1+1等于几",
    "history": []
}, headers=h, timeout=60)
d = r2.json()
print(f"  Reply: {d.get('content','')[:100]}")
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
print(f"  Workflows: {r4.json().get('count', 0)}")

# TEST 2: QQ dispatch
print("\n=== S4-2: QQ dispatch ===")
payload = json.dumps({
    "sender_key": "private_2537134688",
    "text": "你好呀",
    "reply_target": {
        "target_type": "private",
        "target_id": "2537134688",
        "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"}
    }
}).encode("utf-8")
req = urllib.request.Request(
    f"{BASE}/api/v1/robots/items/{ITEM}/dispatch",
    data=payload,
    headers={"Content-Type": "application/json", "X-Termman-Bridge-Token": BRIDGE_TOKEN},
    method="POST"
)
try:
    resp = urllib.request.urlopen(req, timeout=15)
    print(f"  Status: {resp.status}")
    print(f"  Body: {resp.read().decode('utf-8')[:200]}")
except urllib.error.HTTPError as e:
    print(f"  HTTP {e.code}: {e.reason} (expected if robot not loaded)")
except Exception as e:
    print(f"  Error: {e}")

# Wait for QQ processing
time.sleep(10)

# TEST 3: Check session for QQ reply
print("\n=== S4-3: Check QQ reply in session ===")
r2s = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h, timeout=10)
msgs = r2s.json().get("messages", [])
for m in msgs:
    mtype = m.get("type", "")
    content = str(m.get("content", ""))[:150]
    if "你好" in content or mtype == "agent_response":
        print(f"  [{mtype}] {content}")

# Final tokens
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"\nTokens: total={td['total_tokens']}, turns={td['total_turns']}")
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
print(f"Workflows: {r4.json().get('count', 0)}")
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
print(f"Jobs: {r5.json().get('count', 0)}")