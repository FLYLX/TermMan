import requests, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
topics = ["今天天气怎么样","给我讲个笑话","推荐一部电影","什么是人工智能","帮我写首诗","聊聊历史","Python 怎么学","你最喜欢什么","给我个建议","解释下相对论",
          "怎么做饭","聊聊音乐","什么是区块链","推荐本书","今天心情不错","给我讲个故事","什么是量子力学","怎么锻炼身体","聊聊旅游","给我做个计划"]
for i in range(50):
    msg = "CHATMEM %d: %s" % (i, topics[i % 20])
    try:
        requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=15)
    except Exception as e:
        pass
    time.sleep(0.3)
print("fired 50 chats")
