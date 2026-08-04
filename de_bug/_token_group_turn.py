# -*- coding: utf-8 -*-
"""Group-message one-turn token check (mentioned_bot)."""
import requests, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
def totals():
    d = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h, timeout=10).json()
    return d.get("total_prompt_tokens",0), d.get("total_completion_tokens",0), d.get("total_tokens",0), d.get("total_turns",0)
r = requests.delete(f"{BASE}/api/v1/memory/{ITEM}/session", headers=h, timeout=30)
print(f"[clear session] {r.status_code}", flush=True)
p0,c0,t0,n0 = totals()
payload = {
    "sender_key": "group_777666_2537134688",
    "text": "[CQ:at,qq=10001] 3乘4等于多少？直接回答数字",
    "reply_target": {"target_type":"group","target_id":"777666",
        "metadata":{"sender_name":"FLY","sender_id":"2537134688","conversation_type":"group","mentioned_bot":True}},
}
t_start=time.time()
r = requests.post(f"{BASE}/api/v1/robots/{ROBOT}/dispatch", json=payload, headers={"X-Termman-Bridge-Token": BRIDGE}, timeout=60)
print(f"dispatch={r.status_code} {r.json().get('reason')}", flush=True)
last=totals(); stable=0; seen=False
for i in range(100):
    time.sleep(3)
    cur=totals(); el=int(time.time()-t_start)
    if cur[3]>last[3]: print(f"[{el}s] calls {last[3]}->{cur[3]}", flush=True); seen=True
    stable = stable+1 if (cur[2]==last[2] and seen) else 0
    last=cur
    if el>20 and stable>=8: break
p1,c1,t1,n1 = totals()
print(f"RESULT group turn: calls +{n1-n0} | prompt +{p1-p0} | completion +{c1-c0} | total +{t1-t0} | {int(time.time()-t_start)}s", flush=True)
for l in open(r"de_bug\_mock_qq.log", encoding="utf-8", errors="replace").read().splitlines()[-2:]:
    print("  "+l[:200], flush=True)
