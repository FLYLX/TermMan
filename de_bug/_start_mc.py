import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"}, timeout=15)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
msg = ("在终端当前目录(app/items/5)就有 server.jar、eula.txt、server.properties 和 world 目录。"
       "请后台常驻启动 Minecraft 服务器,执行这一条命令:nohup java -Xmx1G -Xms512M -jar server.jar nogui > mc.log 2>&1 & "
       "启动后等大约 15 秒,再执行 tail -n 20 mc.log 把输出告诉我,确认服务器正在加载(出现 Preparing/Loading 或 Done 字样)。"
       "注意必须用 nohup 加 & 让它脱离当前任务常驻运行,不要前台阻塞。")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=120)
print("MC start dispatched:", r2.status_code, str(r2.json().get("content", ""))[:150])
