import requests, json, time, sys, io, urllib.request, threading
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
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode('utf-8'))
    except: return {"error": "timeout"}

def web_send(text):
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": text, "history": []}, headers=h, timeout=25)
        return r.json().get("content", "")[:80]
    except: return "timeout"

print("=== EXTREME STRESS TEST ===\n")

# Phase 1: Rapid fire mixed sources (5 messages in 2 seconds)
print("[Phase 1] Rapid fire 5 msgs mixed sources")
results = []
results.append(("QQ1", qq_send("\u5e2e\u6211\u8dd1\u4e2a sleep 5 && echo done1")))
time.sleep(0.3)
results.append(("Web1", web_send("\u6267\u884c sleep 3 && echo done2")))
time.sleep(0.3)
results.append(("QQ2", qq_send("\u540c\u65f6\u5e2e\u6211\u67e5\u4e00\u4e0b\u78c1\u76d8\u7a7a\u95f4")))
time.sleep(0.3)
results.append(("Web2", web_send("\u518d\u67e5\u4e00\u4e0b\u5185\u5b58")))
time.sleep(0.3)
results.append(("QQ3", qq_send("MC\u670d\u52a1\u5668\u6267\u884c say stress_test")))
for name, res in results:
    status = res.get("reason", res) if isinstance(res, dict) else res
    print(f"  {name}: {status}")

# Phase 2: Wait, then interrupt
print("\n[Phase 2] Wait 15s then interrupt")
time.sleep(15)
print("  Interrupt:", web_send("\u505c\uff0c\u4e0a\u9762\u5168\u53d6\u6d88\uff0c\u544a\u8bc9\u6211\u73b0\u5728\u7ec8\u7aef\u5728\u5e72\u561b")[:80])

# Phase 3: Complex task after chaos
print("\n[Phase 3] Complex task after chaos")
time.sleep(10)
res = qq_send("\u5e2e\u6211\u5199\u4e2a bash \u811a\u672c monitor.sh\uff0c\u6bcf\u79d2\u6253\u5370\u4e00\u6b21\u65f6\u95f4\u5230 /tmp/monitor.log\uff0c\u5199\u5b8c\u540e\u53f0\u8dd1 5 \u79d2\u7136\u540e\u7ed9\u6211\u770b log \u5185\u5bb9")
print(f"  QQ task: {res.get('reason', res)}")

# Phase 4: Wait for everything to settle
print("\n[Phase 4] Waiting 45s for settlement...")
time.sleep(45)

# === VERIFICATION ===
print("\n=== VERIFICATION ===")

# Check for zombie workflows
r3 = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM}", headers=h)
wfs = r3.json().get("workflows", [])
active_wfs = [w for w in wfs if w.get("status") in ("active", "waiting_job", "blocked")]
print(f"\nWorkflows: {len(wfs)} total, {len(active_wfs)} active/blocked")
for wf in active_wfs:
    print(f"  [{wf.get('status')}] {wf.get('objective','')[:60]}")

# Check for running jobs (potential zombies)
r_jobs = requests.get(f"{BASE}/api/v1/items/{ITEM}/jobs", headers=h)
jobs_data = r_jobs.json()
jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get("jobs", jobs_data.get("data", []))
running_jobs = [j for j in jobs if j.get("status") is None or j.get("status") == "running"]
print(f"\nJobs: {len(jobs)} total, {len(running_jobs)} still running")
for j in running_jobs:
    print(f"  elapsed={j.get('elapsed_seconds',0):.0f}s cmd={str(j.get('command',''))[:60]}")

# Check for duplicate responses in session
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=20&offset=0", headers=h)
msgs = r5.json() if isinstance(r5.json(), list) else r5.json().get("messages", [])
assistant_msgs = [str(m.get("content",""))[:100] for m in msgs if m.get("role") == "assistant"]
# Check for near-duplicates
from collections import Counter
duplicates = [(msg, count) for msg, count in Counter(assistant_msgs).items() if count > 1 and len(msg) > 20]
print(f"\nSession: {len(msgs)} msgs, {len(assistant_msgs)} assistant")
if duplicates:
    print(f"  DUPLICATES FOUND: {len(duplicates)}")
    for msg, count in duplicates[:3]:
        print(f"    x{count}: {msg[:80]}")
else:
    print(f"  No duplicate responses ✅")

print("\n=== DONE ===")
