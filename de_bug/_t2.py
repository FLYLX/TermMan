# -*- coding: utf-8 -*-
import json, sys, io, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

print("=== TEST 2: QQ path simple ===")
payload = json.dumps({
    "sender_key": "private_2537134688",
    "text": "在吗",
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
t0 = time.time()
try:
    resp = urllib.request.urlopen(req, timeout=15)
    elapsed = time.time() - t0
    print(f"  Status: {resp.status}, Time: {elapsed:.1f}s")
    print(f"  Body: {resp.read().decode('utf-8')[:200]}")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  Error: {e} ({elapsed:.1f}s)")

# Wait for agent to process
time.sleep(8)

# Check tokens
import requests
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
r3 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10)
td = r3.json()
print(f"  Tokens total: prompt={td['total_prompt_tokens']}, completion={td['total_completion_tokens']}, turns={td['total_turns']}")