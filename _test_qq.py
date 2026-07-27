import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

# Verify the Chinese text is correct before sending
test_text = "小柴，帮我看看现在系统内存还剩多少"
print(f"Text to send: {test_text}")
print(f"Text bytes: {test_text.encode('utf-8')[:50]}")

payload = {
    "sender_key": "private_2537134688",
    "text": test_text,
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

# Send with explicit UTF-8 encoding
import urllib.request
data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request(
    f"{BASE}/api/v1/robots/{ROBOT}/dispatch",
    data=data,
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "X-Termman-Bridge-Token": SECRET,
    },
    method="POST"
)
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode('utf-8'))
print(f"Status: {resp.status}")
print(f"Response: {json.dumps(result, ensure_ascii=False)[:300]}")