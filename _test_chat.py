import urllib.request, urllib.parse, json

ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
BASE = "http://localhost:28888/api/v1"

# Login
data = urllib.parse.urlencode({"username": "admin@example.com", "password": "changethis"}).encode()
req = urllib.request.Request(f"{BASE}/login/access-token", data=data, method="POST")
req.add_header("Content-Type", "application/x-www-form-urlencoded")
resp = urllib.request.urlopen(req, timeout=10)
token = json.loads(resp.read())["access_token"]
print("Token OK")

# Check existing workflows
req2 = urllib.request.Request(f"{BASE}/task-workflows/{ITEM_ID}", method="GET")
req2.add_header("Authorization", f"Bearer {token}")
resp2 = urllib.request.urlopen(req2, timeout=10)
wf = json.loads(resp2.read())
print(f"Workflows BEFORE: {wf.get('count', 0)}")

# Send message
payload = json.dumps({"message": "安装java", "history": []}).encode()
req3 = urllib.request.Request(f"{BASE}/chat/{ITEM_ID}/stream", data=payload, method="POST")
req3.add_header("Authorization", f"Bearer {token}")
req3.add_header("Content-Type", "application/json")
resp3 = urllib.request.urlopen(req3, timeout=120)
content = b""
while True:
    chunk = resp3.read(4096)
    if not chunk:
        break
    content += chunk
    if len(content) > 16000:
        break
text = content.decode("utf-8", errors="replace")
print("=== SSE Response (first 3000 chars) ===")
print(text[:3000])
