# -*- coding: utf-8 -*-
import requests, json, sys, io, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True)

# Cancel any remaining jobs
r5 = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h, timeout=10)
jobs = r5.json()
print(f"Pre-clean jobs: {jobs.get('count', 0)}")

# Check workflows
r4 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h, timeout=10)
wf = r4.json()
print(f"Pre-clean workflows: {wf.get('count', 0)}")

print("\n=== COMPLEX TASK START ===")
msg = "帮我完成这个任务：1)写一个python脚本/tmp/gen.py生成10个1-100的随机数保存到/tmp/nums.txt  2)再写一个/tmp/avg.py读取nums.txt计算平均值和最大值  3)依次运行两个脚本  4)把最终结果汇报给我"
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=120)
d = r2.json()
print(f"Reply: {d.get('content','')[:200]}")
print(f"Time: {time.strftime('%H:%M:%S')}")
import time