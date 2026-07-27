import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Ask agent to run a simple interactive command
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u5728\u7ec8\u7aef\u6267\u884c echo hello_test_123", "history": []},
    headers=h)
print(f"Chat: {r2.status_code} {r2.json().get('content', '')[:150]}")

# Wait for the command to execute and output to come back
time.sleep(8)
print("Done waiting")
