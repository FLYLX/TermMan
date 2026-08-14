"""TermPaws comprehensive test script - tests web chat, QQ dispatch, and complex task."""
import requests, time, json, sys

BASE = "http://127.0.0.1:28888"
ITEM_ID = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
ROBOT_ID = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
BRIDGE_TOKEN = "eWn55fo_kaO2TdnsVbbX3bqxNdQzcwjpR448tA5UYeHFwgk03jH1xdmf2v-PrHNM"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"})
    r.raise_for_status()
    return r.json()["access_token"]

def get_headers(token):
    return {"Authorization": f"Bearer {token}"}

def web_chat(token, message, timeout=120):
    """Send web chat message and return response."""
    r = requests.post(f"{BASE}/api/v1/chat/{ITEM_ID}",
                      json={"message": message, "history": []},
                      headers=get_headers(token), timeout=timeout)
    return r.status_code, r.json() if r.headers.get("content-type","").startswith("application/json") else r.text

def qq_dispatch(message, sender_key="private_2537134688", sender_name="FLY", sender_id="2537134688", timeout=120):
    """Send QQ message via dispatch API."""
    payload = {
        "sender_key": sender_key,
        "text": message,
        "reply_target": {
            "target_type": "private",
            "target_id": sender_id,
            "metadata": {"sender_name": sender_name, "sender_id": sender_id, "conversation_type": "private"}
        }
    }
    r = requests.post(f"{BASE}/api/v1/robots/{ROBOT_ID}/dispatch",
                      json=payload,
                      headers={"X-TermPaws-Bridge-Token": BRIDGE_TOKEN},
                      timeout=timeout)
    return r.status_code, r.json()

def get_workflows(token):
    r = requests.get(f"{BASE}/api/v1/task-workflows/{ITEM_ID}", headers=get_headers(token))
    return r.json()

def get_jobs(token):
    r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/jobs", headers=get_headers(token))
    return r.json()

def get_token_stats(token):
    r = requests.get(f"{BASE}/api/v1/items/{ITEM_ID}/token-usage", headers=get_headers(token))
    return r.json()

def get_session_history(token, limit=10):
    r = requests.get(f"{BASE}/api/v1/chat/{ITEM_ID}/history",
                     headers=get_headers(token), params={"limit": limit})
    if r.status_code == 200:
        return r.json()
    return None

def wait_for_workflow_complete(token, timeout=300, poll_interval=5):
    """Wait for all workflows to complete/cancel."""
    start = time.time()
    while time.time() - start < timeout:
        wf_data = get_workflows(token)
        workflows = wf_data.get("workflows", [])
        active = [w for w in workflows if w.get("status") in ("running", "pending")]
        if not active:
            return True, workflows
        for w in active:
            steps = w.get("steps", [])
            done = sum(1 for s in steps if s.get("status") in ("completed", "cancelled", "failed"))
            total = len(steps)
            print(f"  [{int(time.time()-start)}s] workflow {w['id'][:8]}: {w['status']} ({done}/{total} steps)")
        time.sleep(poll_interval)
    return False, get_workflows(token).get("workflows", [])

# ============ MAIN ============
print("=" * 60)
print("TermPaws Comprehensive Test")
print("=" * 60)

token = login()
print(f"[OK] Logged in")

# Record baseline tokens
baseline = get_token_stats(token)
print(f"[BASELINE] Tokens: {baseline.get('total_tokens', 0)}, Turns: {baseline.get('total_turns', 0)}")

# ---- TEST 1: Simple web chat ----
print("\n" + "=" * 60)
print("TEST 1: Simple web chat (1+1)")
print("=" * 60)
t0 = time.time()
status, resp = web_chat(token, "1+1等于几")
elapsed = time.time() - t0
print(f"  Status: {status}, Time: {elapsed:.1f}s")
if isinstance(resp, dict):
    content = resp.get("content", "")
    print(f"  Reply: {content[:200]}")
    # Check no workflow created
    wf = get_workflows(token)
    wf_count = wf.get("count", 0)
    print(f"  Workflows after: {wf_count} (expect 0)")
    if wf_count > 0:
        print("  [WARN] Workflow created for simple chat!")
    else:
        print("  [PASS] No workflow for simple chat")
else:
    print(f"  Raw: {str(resp)[:200]}")

# ---- TEST 2: QQ dispatch ----
print("\n" + "=" * 60)
print("TEST 2: QQ dispatch (你好呀)")
print("=" * 60)
t0 = time.time()
status, resp = qq_dispatch("你好呀，今天心情怎么样")
elapsed = time.time() - t0
print(f"  Status: {status}, Time: {elapsed:.1f}s")
if isinstance(resp, dict):
    print(f"  Success: {resp.get('success')}")
    print(f"  Ignored: {resp.get('ignored')}")
    print(f"  Reason: {resp.get('reason')}")
    chunks = resp.get("reply_chunks", [])
    if chunks:
        print(f"  Reply chunks: {len(chunks)}")
        for c in chunks[:3]:
            print(f"    -> {c[:150]}")
    else:
        print("  [INFO] No reply chunks (reply may come via bridge send)")
    # Check no workflow
    wf = get_workflows(token)
    wf_count = wf.get("count", 0)
    print(f"  Workflows after: {wf_count} (expect 0)")
else:
    print(f"  Raw: {str(resp)[:200]}")

# ---- TEST 3: Complex task (install jq) ----
print("\n" + "=" * 60)
print("TEST 3: Complex task - install jq")
print("=" * 60)
t0 = time.time()
status, resp = web_chat(token, "帮我安装 jq，装完验证一下版本", timeout=180)
elapsed = time.time() - t0
print(f"  Status: {status}, Time: {elapsed:.1f}s")
if isinstance(resp, dict):
    content = resp.get("content", "")
    print(f"  Reply: {content[:300]}")

# Wait for workflow to complete
print("  Waiting for workflow completion...")
completed, workflows = wait_for_workflow_complete(token, timeout=300, poll_interval=8)
if completed:
    print("  [PASS] Workflow completed")
else:
    print("  [WARN] Workflow did not complete in time")

# Check workflow details
for w in workflows:
    print(f"\n  Workflow: {w['id'][:12]} | Status: {w['status']} | Title: {w.get('title','')}")
    for s in w.get("steps", []):
        print(f"    Step {s.get('order')}: {s.get('title')} [{s.get('status')}] attempts={s.get('attempts',0)}")

# Check jobs
jobs_data = get_jobs(token)
jobs = jobs_data.get("jobs", [])
print(f"\n  Total jobs: {len(jobs)}")
for j in jobs:
    print(f"    {j['id'][:12]} | {j['status']} | {j.get('command','')[:80]}")

# Check for duplicate commands
commands = [j.get("command","") for j in jobs]
from collections import Counter
dupes = {cmd: cnt for cmd, cnt in Counter(commands).items() if cnt > 1}
if dupes:
    print(f"  [WARN] Duplicate commands: {dupes}")
else:
    print("  [PASS] No duplicate commands")

# ---- Final token stats ----
print("\n" + "=" * 60)
print("TOKEN USAGE")
print("=" * 60)
final = get_token_stats(token)
total_tokens = final.get("total_tokens", 0) - baseline.get("total_tokens", 0)
total_turns = final.get("total_turns", 0) - baseline.get("total_turns", 0)
prompt = final.get("total_prompt_tokens", 0) - baseline.get("total_prompt_tokens", 0)
completion = final.get("total_completion_tokens", 0) - baseline.get("total_completion_tokens", 0)
print(f"  Total tokens used: {total_tokens}")
print(f"  Prompt: {prompt}, Completion: {completion}")
print(f"  Ratio: {prompt/max(completion,1):.1f}:1")
print(f"  Turns: {total_turns}")
for m in final.get("models", []):
    print(f"  Model {m['model']}: {m['total_tokens']} tokens, {m['turns']} turns")

print("\n[DONE] All tests completed")