import requests, json, time

BASE = "http://127.0.0.1:28888"
ITEM = "6a88dadd-3f93-4dfc-804a-dd79425f45ee"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

# Login
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# QQ dispatch - ask who's online (should NOT broadcast to MC server)
import urllib.request
payload = {
    "sender_key": "group_770362397_2537134688",
    "text": "\u8c01\u5728\u7ebf",
    "reply_target": {
        "target_type": "group",
        "target_id": "770362397",
        "metadata": {
            "sender_name": "FLY",
            "sender_id": "2537134688",
            "conversation_type": "group",
            "group_id": "770362397"
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
print(f"Dispatch status: {resp.status}")
print(resp.read().decode('utf-8')[:500])
