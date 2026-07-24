import urllib.request, urllib.parse, json

ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
BASE = "http://localhost:28888/api/v1"

data = urllib.parse.urlencode({"username": "admin@example.com", "password": "changethis"}).encode()
req = urllib.request.Request(f"{BASE}/login/access-token", data=data, method="POST")
req.add_header("Content-Type", "application/x-www-form-urlencoded")
resp = urllib.request.urlopen(req, timeout=10)
token = json.loads(resp.read())["access_token"]

req2 = urllib.request.Request(f"{BASE}/task-workflows/{ITEM_ID}", method="GET")
req2.add_header("Authorization", f"Bearer {token}")
resp2 = urllib.request.urlopen(req2, timeout=10)
wf = json.loads(resp2.read())
print(json.dumps(wf, ensure_ascii=False, indent=2))
