import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
msg = "在终端执行命令 java -version,把完整输出原样告诉我,不要做别的"
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=120)
print("status:", r2.status_code)
print("content:", str(r2.json().get("content", ""))[:600])
