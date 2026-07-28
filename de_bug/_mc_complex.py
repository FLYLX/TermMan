import requests, json, time, sys, io, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

def qq_send(text):
    payload = {"sender_key": "private_2537134688", "text": text,
        "reply_target": {"target_type": "private", "target_id": "2537134688",
            "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"}}}
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", data=data,
        headers={"Content-Type": "application/json; charset=utf-8", "X-Termman-Bridge-Token": SECRET})
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode('utf-8'))

# Complex MC interaction task
print("=== MC Server Interaction ===")
res = qq_send("\u5e2e\u6211\u5728MC\u670d\u52a1\u5668\u91cc\u505a\u8fd9\u4e9b\uff1a1.\u8bbe\u7f6e\u65f6\u95f4\u4e3a\u767d\u5929 2.\u8bbe\u7f6e\u5929\u6c14\u4e3a\u6674\u5929 3.\u5f00\u542fkeepInventory 4.\u5e7f\u64ad\u4e00\u53e5\u201c\u670d\u52a1\u5668\u5df2\u914d\u7f6e\u5b8c\u6bd5\uff0c\u6b22\u8fce\u5165\u670d\u201d 5.\u6700\u540e\u67e5\u4e00\u4e0b\u5728\u7ebf\u73a9\u5bb6")
print(f"  Sent: {res.get('success')} {res.get('reason')}")

# Wait for multi-step interaction
print("Waiting 40s...")
time.sleep(40)

# Check session
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=12&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
print(f"\nSession ({len(msgs)} msgs):")
for m in msgs:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:150]
    print(f"  [{role}] {content}")
