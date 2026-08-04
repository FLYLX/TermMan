import requests
BASE = 'http://127.0.0.1:28888'
ITEM = 'ea52de0c-51b7-4b49-a43d-985ed2e09579'
r = requests.post(f'{BASE}/api/v1/login/access-token', data={'username': 'admin@example.com', 'password': 'changethis'})
h = {'Authorization': f'Bearer {r.json()["access_token"]}'}
r2 = requests.get(f'{BASE}/api/v1/items/{ITEM}/plan', headers=h, timeout=10)
plan = r2.json().get('plan', [])
if plan:
    for s in plan:
        print(f'  [{s.get("status")}] {s.get("step")}')
else:
    print('no plan')
