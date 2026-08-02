import requests
BASE = 'http://127.0.0.1:28888'
ITEM = 'ea52de0c-51b7-4b49-a43d-985ed2e09579'
r = requests.post(f'{BASE}/api/v1/login/access-token', data={'username': 'admin@example.com', 'password': 'changethis'})
h = {'Authorization': f'Bearer {r.json()["access_token"]}'}

# Check plan
r2 = requests.get(f'{BASE}/api/v1/items/{ITEM}/plan', headers=h, timeout=10)
print('plan status:', r2.status_code)
plan_data = r2.json()
plan = plan_data.get('plan', [])
if plan:
    for j, s in enumerate(plan):
        print(f'  {j+1}. [{s.get("status","?")}] {s.get("step","?")}')
else:
    print('  (no plan)')

print()

# Check tickets
r3 = requests.get(f'{BASE}/api/v1/items/{ITEM}/reply-tickets', headers=h, timeout=10)
tdata = r3.json()
if isinstance(tdata, list):
    for t in tdata[:8]:
        p = t.get('plan', [])
        ps = '; '.join(f'[{s.get("status")}]{s.get("step","")[:25]}' for s in p) if p else '(none)'
        print(f'ticket {t.get("ticket_id","")[:8]}: st={t.get("status")} req={t.get("request_message","")[:40]} plan={ps}')
