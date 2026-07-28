import requests, json, time, sys, io, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
SECRET = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def qq_send(text):
    payload = {"sender_key": "private_2537134688", "text": text,
        "reply_target": {"target_type": "private", "target_id": "2537134688",
            "metadata": {"sender_name": "FLY", "sender_id": "2537134688", "conversation_type": "private"}}}
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", data=data,
        headers={"Content-Type": "application/json; charset=utf-8", "X-Termman-Bridge-Token": SECRET})
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode('utf-8'))

def web_send(text):
    r = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": text, "history": []}, headers=h, timeout=30)
    return r.json().get("content", "")[:100]

# Clear token table first
import subprocess
subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys;sys.path.insert(0,'/app/backend');from sqlmodel import Session,text;from app.core.db import engine;s=Session(engine);s.exec(text('DELETE FROM token_usage_record'));s.commit();s.close()"],
    capture_output=True, timeout=10)
print("Token table cleared\n")
time.sleep(2)

# TEST 1: QQ simple chat
print("T1: QQ chat")
res = qq_send("\u5c0f\u67f4\u5728\u5417")
print(f"  {res.get('success')} {res.get('reason','')}")
time.sleep(8)

# TEST 2: QQ ask to do something
print("T2: QQ task")
res = qq_send("\u5e2e\u6211\u770b\u770b\u5f53\u524d\u76ee\u5f55\u6709\u4ec0\u4e48\u6587\u4ef6")
print(f"  {res.get('success')} {res.get('reason','')}")
time.sleep(12)

# TEST 3: Web chat quick question
print("T3: Web quick")
res = web_send("\u4eca\u5929\u5929\u6c14\u600e\u4e48\u6837")
print(f"  {res}")
time.sleep(3)

# TEST 4: Web complex task
print("T4: Web task")
res = web_send("\u5e2e\u6211\u5199\u4e2a python \u811a\u672c\u8ba1\u7b97\u6590\u6ce2\u90a3\u5951\u6570\u5217\u524d20\u9879\uff0c\u5199\u5b8c\u8dd1\u4e00\u4e0b\u7ed9\u6211\u770b\u7ed3\u679c")
print(f"  {res}")
time.sleep(15)

# TEST 5: QQ another question
print("T5: QQ question")
res = qq_send("\u521a\u624d\u90a3\u4e2a\u6590\u6ce2\u90a3\u5951\u7ed3\u679c\u662f\u5565")
print(f"  {res.get('success')} {res.get('reason','')}")
time.sleep(10)

# Final token check
print("\n=== FINAL TOKENS ===")
r4 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
data = r4.json()
turns = data.get('total_turns',0)
prompt = data.get('total_prompt_tokens',0)
comp = data.get('total_completion_tokens',0)
total = data.get('total_tokens',0)
print(f"Total: {total} | Turns: {turns} | Prompt: {prompt} | Comp: {comp}")
if comp > 0:
    print(f"Ratio: {prompt/comp:.1f}:1 | Per turn: {total//max(turns,1)}")
