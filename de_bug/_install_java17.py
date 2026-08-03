import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
msg = ("帮我在终端安装 Java 17 运行环境:执行 apt-get update 然后 apt-get install -y "
       "openjdk-17-jre-headless(如果 apt 源慢或失败,可尝试先换阿里云镜像)。装完执行 java -version 验证,把版本号告诉我。")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=120)
print("install dispatched:", r2.status_code, str(r2.json().get("content", ""))[:150])
