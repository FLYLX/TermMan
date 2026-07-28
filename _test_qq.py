import requests, json, time, sys, io, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

# QQ dispatch
payload = {
    "sender_key": "private_2537134688",
    "text": "\u5c0f\u67f4\uff0c\u5e2e\u6211\u67e5\u4e00\u4e0b\u670d\u52a1\u5668\u5185\u5b58",
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
        "X-Termman-Bridge-Token": SECRET
    }
)
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode('utf-8'))
print(f"Dispatch: {resp.status}")
print(f"  success: {result.get('success')}")
print(f"  ignored: {result.get('ignored')}")
print(f"  reason: {result.get('reason')}")
if result.get('reply_chunks'):
    for chunk in result['reply_chunks'][:3]:
        print(f"  reply: {str(chunk)[:150]}")

# Wait and check session
time.sleep(12)

r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=4&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
print(f"\nSession:")
for m in msgs[-3:]:
    print(f"  [{m.get('role')}] {str(m.get('content',''))[:200]}")
