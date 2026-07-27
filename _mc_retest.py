import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check old workflows
r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wf = r.json()
print(f"Old workflows: {wf.get('count', 0)}")
for w in wf.get("workflows", []):
    print(f"  {w.get('workflow_id','?')[:12]} status={w.get('status')} obj={w.get('objective','')[:60]}")

# Start terminal
print("\n=== Starting terminal ===")
r = requests.post(f"{BASE}/api/v1/items/{ITEM}/start", headers=h)
print(f"Start: {r.status_code} {r.text[:200]}")
time.sleep(3)

# Send MC server task
msg = "帮我在终端里启动之前下载的MC服务器，server.jar在items/5目录下，用java -jar server.jar nogui启动，启动后等它加载完告诉我"
print(f"\n=== Sending: {msg[:60]}... ===")
r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": msg, "history": []},
    headers=h, timeout=120)
print(f"Status: {r.status_code}")
data = r.json()
print(f"Response: {data.get('content', '')[:300]}")