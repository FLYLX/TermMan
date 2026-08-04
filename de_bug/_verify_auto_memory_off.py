# -*- coding: utf-8 -*-
import requests, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
def mems():
    r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories?limit=200", headers=h, timeout=20)
    d = r.json()
    m = d.get("memories") if isinstance(d, dict) else d
    if isinstance(m, dict): m = m.get("memories", [])
    return m or []
def dispatch(text):
    payload = {"sender_key": "private_2537134688", "text": text,
        "reply_target": {"target_type":"private","target_id":"2537134688",
            "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}}}
    return requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)

before = mems()
print(f"memories before: {len(before)}")

# 1) task-instruction message (used to create dirty auto memory)
r = dispatch("帮我完成一组任务并汇报：1) 创建目录 /tmp/mem_check 2) 验证目录存在")
print("task dispatch:", r.status_code, r.json().get("reason"))
time.sleep(45)
after_task = mems()
new_task = [m for m in after_task if str(m.get("id")) not in {str(x.get("id")) for x in before}]
print(f"memories after task: {len(after_task)} | NEW: {len(new_task)}")
for m in new_task: print("  NEW:", str(m.get("content"))[:80], "| source:", (m.get("metadata") or {}).get("source"))

# 2) explicit remember request (should still persist)
r = dispatch("记住：我喜欢在任务完成后喝可乐")
print("explicit dispatch:", r.status_code, r.json().get("reason"))
time.sleep(25)
after_explicit = mems()
new_explicit = [m for m in after_explicit if str(m.get("id")) not in {str(x.get("id")) for x in after_task}]
print(f"memories after explicit: {len(after_explicit)} | NEW: {len(new_explicit)}")
for m in new_explicit: print("  NEW:", str(m.get("content"))[:80], "| source:", (m.get("metadata") or {}).get("source"))
