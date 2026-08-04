# -*- coding: utf-8 -*-
import requests, sys, io, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
LOG = r"de_bug\_mock_qq.log"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
def plan():
    r = requests.get(f"{BASE}/api/v1/items/{ITEM}/plan", headers=h, timeout=10)
    d = r.json()
    return d.get("plan") or []
def outbox():
    return open(LOG, encoding="utf-8", errors="replace").read().splitlines()
pre = outbox()
payload = {
    "sender_key": "private_2537134688",
    "text": "帮我创建目录 /tmp/plan_smoke，然后验证它存在，完成后告诉我",
    "reply_target": {"target_type":"private","target_id":"2537134688",
        "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}},
}
t_start=time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"dispatch={r.status_code} {r.json().get('reason')}", flush=True)
seen_plan = None
max_steps = 0
for i in range(80):
    time.sleep(2)
    p = plan()
    if p:
        if seen_plan is None:
            seen_plan = int(time.time()-t_start)
            print(f"[{seen_plan}s] PLAN APPEARED: {json.dumps(p, ensure_ascii=False)[:200]}", flush=True)
        max_steps = max(max_steps, len(p))
        last_status = p[-1].get('status') if p else ''
        if i % 5 == 0:
            print(f"[{int(time.time()-t_start)}s] plan steps={len(p)} last={last_status}", flush=True)
    elif seen_plan is not None:
        print(f"[{int(time.time()-t_start)}s] PLAN CLEARED (removed from table)", flush=True)
        break
post = outbox()
new = post[len(pre):]
sends = [l for l in new if "send_private_msg" in l or "send_group_msg" in l]
print(f"\nRESULT: {int(time.time()-t_start)}s | plan first seen at {seen_plan}s | SENDS={len(sends)}", flush=True)
for l in sends: print("  "+l[:260], flush=True)
