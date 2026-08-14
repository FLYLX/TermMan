import requests, json, time, sys, io, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Clear tokens
import subprocess
subprocess.run(["docker", "exec", "TermPaws-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True, timeout=10)
print("Cleared\n")
time.sleep(2)

# SUPER COMPLEX TASK via QQ
task = ("\u5e2e\u6211\u505a\u4ee5\u4e0b\u4e8b\u60c5\uff1a"
    "1.\u5199\u4e00\u4e2a python \u811a\u672c server_info.py\uff0c\u529f\u80fd\u662f\u6253\u5370\u7cfb\u7edf\u5185\u5b58\u3001\u78c1\u76d8\u3001CPU\u4fe1\u606f "
    "2.\u8dd1\u4e00\u4e0b\u786e\u8ba4\u80fd\u7528 "
    "3.\u518d\u5199\u4e00\u4e2a cron \u4efb\u52a1\u6bcf\u5206\u949f\u6267\u884c\u8fd9\u4e2a\u811a\u672c\u5e76\u5199\u5165 /tmp/syslog.txt "
    "4.\u9a8c\u8bc1 cron \u751f\u6548 "
    "5.\u5b8c\u6210\u540e\u544a\u8bc9\u6211\u7ed3\u679c")

payload = {"sender_key": "private_2537134688", "text": task,
    "reply_target": {"target_type": "private", "target_id": "2537134688",
        "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"}}}
data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", data=data,
    headers={"Content-Type": "application/json; charset=utf-8", "X-TermPaws-Bridge-Token": SECRET})
resp = urllib.request.urlopen(req, timeout=10)
result = json.loads(resp.read().decode('utf-8'))
print(f"QQ dispatch: {result.get('success')} {result.get('reason')}")
print(f"Task: {task[:80]}...")
