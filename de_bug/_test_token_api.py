import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Test token usage API
r2 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
print(f"Token API: {r2.status_code}")
print(json.dumps(r2.json(), indent=2, ensure_ascii=False)[:500])

# Send a quick chat to generate some token usage
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "hi", "history": []},
    headers={**h, "Content-Type": "application/json"})
print(f"\nChat: {r3.status_code}")

import time; time.sleep(5)

# Check again
r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
print(f"\nAfter chat: turns={data.get('total_turns')}, tokens={data.get('total_tokens')}")
for m in data.get("models", []):
    print(f"  {m['model']}: {m['total_tokens']} tokens, {m['turns']} turns")
