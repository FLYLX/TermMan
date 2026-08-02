import requests, time

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f'{BASE}/api/v1/login/access-token', data={'username': 'admin@example.com', 'password': 'changethis'})
h = {'Authorization': f'Bearer {r.json()["access_token"]}'}

for i in range(36):
    time.sleep(15)
    el = (i+1)*15
    try:
        r2 = requests.get(f'{BASE}/api/v1/items/{ITEM}/plan', headers=h, timeout=10)
        plan = r2.json().get('plan', [])
        if plan:
            steps = " | ".join(f"{j+1}.[{s.get('status','?')}] {s.get('step','?')[:25]}" for j,s in enumerate(plan))
            print(f"[{el}s] plan({len(plan)}): {steps}", flush=True)
        else:
            print(f"[{el}s] plan cleared (done!)", flush=True)
            break
    except Exception as e:
        print(f"[{el}s] err: {e}", flush=True)

print("\n=== Final ===", flush=True)
r3 = requests.get(f'{BASE}/api/v1/items/{ITEM}/plan', headers=h, timeout=10)
plan = r3.json().get('plan', [])
if plan:
    for j,s in enumerate(plan):
        print(f"  {j+1}. [{s.get('status','?')}] {s.get('step','?')}", flush=True)
else:
    print("  (no plan - cleared = all done)", flush=True)
