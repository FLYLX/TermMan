import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
topics = ["天气","笑话","电影","人工智能","写诗","历史","Python","音乐","建议","相对论","做饭","旅游","故事","量子","锻炼","读书","游戏","科技","自然","美食"]
for i in range(100):
    msg = "CHATCURVE %d: 聊聊%s" % (i, topics[i % 20])
    try:
        requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=8)
    except Exception:
        pass
print("fired 100 chats")
