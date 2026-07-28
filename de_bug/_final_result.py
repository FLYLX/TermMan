import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
print(f"=== FINAL TOKEN COUNT ===")
print(f"Total: {data.get('total_tokens',0)} tokens")
print(f"Turns: {data.get('total_turns',0)}")
print(f"Prompt: {data.get('total_prompt_tokens',0)}")
print(f"Completion: {data.get('total_completion_tokens',0)}")
if data.get('total_completion_tokens', 0) > 0:
    ratio = data['total_prompt_tokens'] / data['total_completion_tokens']
    print(f"Ratio: {ratio:.1f}:1")

r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
for wf in r3.json().get("workflows", []):
    print(f"\nWF: status={wf.get('status')}")
    for i, s in enumerate(wf.get("steps", [])):
        print(f"  {i+1}. [{s.get('status')}] {s.get('title')}")
