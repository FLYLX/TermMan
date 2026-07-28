import requests, json, time

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Tell it OpenJDK 21 is fine, just finish
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "OpenJDK 21\u4e0d\u7528\u7ba1\uff0c\u53ea\u8981Corretto\u5220\u5e72\u51c0\u5c31\u884c\uff0c\u4efb\u52a1\u5b8c\u6210", "history": []},
    headers=h)
print("Resolve:", r2.status_code, r2.json().get("content", "")[:200])

time.sleep(5)

# Now test fresh install - nginx
print("\n--- Starting nginx install test ---")
r3 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
    json={"message": "\u5e2e\u6211\u5b89\u88c5 nginx\uff0c\u88c5\u5b8c\u542f\u52a8\u5b83\uff0c\u7136\u540e\u9a8c\u8bc1 curl localhost \u80fd\u8fd4\u56de\u5185\u5bb9", "history": []},
    headers=h)
print("Nginx:", r3.status_code, r3.json().get("content", "")[:200])
