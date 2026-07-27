import requests, json

BASE = "http://127.0.0.1:28888"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

r2 = requests.get(f"{BASE}/api/v1/items/", headers=h)
data = r2.json()
print(type(data).__name__)
if isinstance(data, dict):
    print(list(data.keys())[:10])
    for k, v in data.items():
        if isinstance(v, list):
            for item in v[:5]:
                if isinstance(item, dict):
                    print(f"  {item.get('id')} - {item.get('name')}")
            break
elif isinstance(data, list):
    for item in data[:5]:
        print(f"  {item.get('id')} - {item.get('name')}")
