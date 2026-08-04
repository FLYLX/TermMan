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
    return r.json().get("plan") or []
def outbox():
    return open(LOG, encoding="utf-8", errors="replace").read().splitlines()
pre = outbox()
payload = {
    "sender_key": "private_2537134688",
    "text": "给我一个计划并执行：第一步创建 /tmp/plan_demo2 目录，第二步在里面写 hello.txt 内容是 hi，第三步验证文件内容，每步都用update_plan记录进度",
    "reply_target": {"target_type":"private","target_id":"2537134688",
        "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"private"}},
}
t_start=time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"dispatch={r.status_code} {r.json().get('reason')}", flush=True)
seen_plan_at = None
cleared_at = None
snapshots = []
for i in range(150):
    time.sleep(1)
    p = plan()
    if p:
        if seen_plan_at is None:
            seen_plan_at = int(time.time()-t_start)
        sig = json.dumps([(s.get('step'),s.get('status')) for s in p], ensure_ascii=False)
        if not snapshots or snapshots[-1] != sig:
            snapshots.append(sig)
            print(f"[{int(time.time()-t_start)}s] PLAN: {sig[:220]}", flush=True)
    elif seen_plan_at is not None and cleared_at is None:
        cleared_at = int(time.time()-t_start)
        print(f"[{cleared_at}s] PLAN CLEARED", flush=True)
        break
post = outbox()
new = post[len(pre):]
sends = [l for l in new if "send_private_msg" in l or "send_group_msg" in l]
print(f"\nRESULT: {int(time.time()-t_start)}s | plan shown at {seen_plan_at}s | cleared at {cleared_at} | SENDS={len(sends)}", flush=True)
for l in sends: print("  "+l[:260], flush=True)
