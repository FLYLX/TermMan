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
print(f"Total: {total} tokens | {turns} turns")
print(f"Prompt: {prompt} | Completion: {comp}")
if comp > 0:
    print(f"Ratio: {prompt/comp:.1f}:1")
    print(f"Per turn prompt: {prompt//max(turns,1)}")
    print(f"Per turn total: {total//max(turns,1)}")
print(f"\nModels:")
for m in data.get("models", []):
    print(f"  {m['model']}: {m['total_tokens']} tokens, {m['turns']} turns, ratio {m['prompt_tokens']/max(m['completion_tokens'],1):.1f}:1")
