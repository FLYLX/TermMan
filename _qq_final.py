import requests, json, sys, io, time
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

# QQ dispatch - ask about system status
import urllib.request
payload = {
    "sender_key": "private_2537134688",
    "text": "小柴，帮我跑一下uptime和df -h看看服务器状态",
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
        "X-Termman-Bridge-Token": SECRET,
    },
    method="POST"
)
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode('utf-8'))
print(f"QQ dispatch: {json.dumps(result, ensure_ascii=False)[:200]}")

print("Waiting 30s...")
time.sleep(30)

after = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=1&offset=0", headers=h).json().get("total", 0)
print(f"Session: {after} (delta={after-baseline})")

# Last 5
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=5&offset=0", headers=h)
data2 = r.json()
msgs = data2 if isinstance(data2, list) else data2.get("messages", data2.get("history", []))
for i, m in enumerate(msgs):
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:250]
    ticket = m.get("reply_ticket_id", "")
    print(f"[{i}] {role} ticket={ticket[:12] if ticket else ''}: {content}")
    print()