import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Token usage
r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
print(f"=== TOKEN RESULT ===")
print(f"Total: {data.get('total_tokens')} tokens, {data.get('total_turns')} turns")
print(f"Prompt: {data.get('total_prompt_tokens')}, Completion: {data.get('total_completion_tokens')}")
if data.get('total_completion_tokens', 0) > 0:
    ratio = data['total_prompt_tokens'] / data['total_completion_tokens']
    per_turn = data['total_prompt_tokens'] / max(data['total_turns'], 1)
    print(f"Ratio: {ratio:.1f}:1")
    print(f"Per turn prompt: {per_turn:.0f}")

# Workflow
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
for wf in r3.json().get("workflows", []):
    print(f"\nWF: status={wf.get('status')} obj={wf.get('objective','')[:60]}")
    for i, s in enumerate(wf.get("steps", [])):
        print(f"  {i+1}. [{s.get('status')}] {s.get('title')}")
