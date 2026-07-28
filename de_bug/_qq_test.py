# -*- coding: utf-8 -*-
import requests, json, sys, io, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check robot status
print("=== Robot/Bridge status ===")
try:
    r2 = requests.get(f"{BASE}/api/v1/robots/items/{ITEM}/conversation-controllers", headers=h, timeout=10)
    print(f"Controllers: {r2.status_code} {r2.text[:300]}")
except Exception as e:
    print(f"Error: {e}")

# Try QQ dispatch
print("\n=== QQ dispatch ===")
payload = json.dumps({
    "sender_key": "private_2537134688",
    "text": "小柴在吗",
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
    resp = urllib.request.urlopen(req, timeout=30)
    print(f"Status: {resp.status}")
    body = resp.read().decode("utf-8")
    print(f"Body: {body[:300]}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8") if e.fp else ""
    print(f"HTTP {e.code}: {e.reason}")
    print(f"Body: {body[:300]}")
except Exception as e:
    print(f"Error: {e}")

# Wait and check session for QQ reply
time.sleep(10)
print("\n=== Session check ===")
r3 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h, timeout=10)
msgs = r3.json().get("messages", [])
for m in msgs:
    mtype = m.get("type", "")
    content = str(m.get("content", ""))[:200]
    print(f"  [{mtype}] {content}")