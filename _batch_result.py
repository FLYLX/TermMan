import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
turns = data.get('total_turns',0)
prompt = data.get('total_prompt_tokens',0)
comp = data.get('total_completion_tokens',0)
total = data.get('total_tokens',0)
print(f"Total: {total} | Turns: {turns}")
print(f"Prompt: {prompt} | Comp: {comp}")
if comp > 0:
    print(f"Ratio: {prompt/comp:.1f}:1 | Per turn: {total//max(turns,1)}")

# Check session for responses
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=8&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
print(f"\nRecent ({len(msgs)}):")
for m in msgs[-6:]:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:150]
    print(f"  [{role}] {content}")
