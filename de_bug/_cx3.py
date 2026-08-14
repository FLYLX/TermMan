# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
subprocess.run(["docker", "exec", "TermPaws-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

print("=== COMPLEX TEST 2: multi-step with verification ===")
msg = "帮我做这几件事：1)在/tmp下创建一个test_dir目录  2)写一个bash脚本/tmp/test_dir/backup.sh，功能是备份/tmp/nums.txt到/tmp/test_dir/nums_backup.txt  3)运行这个脚本  4)验证备份文件存在且内容一致  5)汇报结果"
t0 = time.time()
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=120)
d = r2.json()
print(f"Reply: {d.get('content','')[:200]}")
print(f"HTTP time: {time.time()-t0:.1f}s")