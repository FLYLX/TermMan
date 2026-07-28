import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

try:
    r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "\u5b89\u88c5java21", "history": []}, headers=h, timeout=25)
    print(f"Sent: {r2.status_code} {r2.json().get('content','')[:60]}")
except Exception as e:
    print(f"Sent: {e}")

time.sleep(25)

r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
turns = data.get('total_turns',0)
prompt = data.get('total_prompt_tokens',0)
comp = data.get('total_completion_tokens',0)
total = data.get('total_tokens',0)
print(f"\nTurns: {turns} | Total: {total} | Prompt: {prompt} | Comp: {comp}")
if turns > 0:
    print(f"Per turn prompt: {prompt//turns}")
if comp > 0:
    print(f"Ratio: {prompt/comp:.1f}:1")
