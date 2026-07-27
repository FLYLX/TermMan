import requests, json, time, urllib.request

BASE = "http://127.0.0.1:28888"
ITEM = "6a88dadd-3f93-4dfc-804a-dd79425f45ee"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

# Login
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Check conversation controllers
r2 = requests.get(f"{BASE}/api/v1/robots/items/{ITEM}/conversation-controllers", headers=h)
print("Controllers:", json.dumps(r2.json(), ensure_ascii=False, indent=2)[:1000])
