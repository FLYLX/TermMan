import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# First stop any running MC server
r1 = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "\u5148 stop \u505c\u6389\u5f53\u524d MC \u670d\u52a1\u5668\uff0c\u7136\u540e\u91cd\u65b0\u7528 java -jar server.jar nogui \u542f\u52a8\uff0c\u542f\u52a8\u6210\u529f\u544a\u8bc9\u6211", "history": []},
    headers=h)
print(f"Task: {r1.status_code} {r1.json().get('content','')[:100]}")

# Wait for task to complete
print("Waiting 90s...")
time.sleep(90)

# Check token usage
r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
print(f"\n=== TOKEN RESULT ===")
print(f"Total: {data.get('total_tokens')} tokens, {data.get('total_turns')} turns")
print(f"Prompt: {data.get('total_prompt_tokens')}, Completion: {data.get('total_completion_tokens')}")
if data.get('total_completion_tokens', 0) > 0:
    ratio = data['total_prompt_tokens'] / data['total_completion_tokens']
    per_turn = data['total_prompt_tokens'] / data['total_turns']
    print(f"Ratio: {ratio:.1f}:1")
    print(f"Per turn prompt: {per_turn:.0f}")

# Check workflow
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
for wf in r3.json().get("workflows", []):
    print(f"\nWF: status={wf.get('status')}")
    for i, s in enumerate(wf.get("steps", [])):
        print(f"  {i+1}. [{s.get('status')}] {s.get('title')}")
