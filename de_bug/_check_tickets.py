import requests
BASE = 'http://127.0.0.1:28888'
ITEM = 'ea52de0c-51b7-4b49-a43d-985ed2e09579'
r = requests.post(f'{BASE}/api/v1/login/access-token', data={'username': 'admin@example.com', 'password': 'changethis'})
h = {'Authorization': f'Bearer {r.json()["access_token"]}'}
r2 = requests.get(f'{BASE}/api/v1/items/{ITEM}/reply-tickets', headers=h, timeout=10)
data = r2.json()
tickets = data if isinstance(data, list) else data.get('tickets', [])
for t in tickets[:6]:
    print(t.get('ticket_id', '')[:8], '|', t.get('status'), '|', t.get('source_type'), '| ext_report:', t.get('external_report_sent'), '| req:', (t.get('request_message') or '')[:45])
