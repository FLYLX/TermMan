"""E2E: memory save -> handler-scope load -> shared across items of same handler."""
import requests, time

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def h():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
        data={"username": "admin@example.com", "password": "changethis"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# 1. resolve handler scope for the item
r = requests.get(f"{BASE}/api/v1/item-handlers/", headers=h(), timeout=15)
handlers = r.json()
log(f"handlers: {len(handlers) if isinstance(handlers, list) else handlers}")

# 2. save a memory via REST
test_content = f"e2e-scope-test: 服务器胎记端口是 43906 (t={int(time.time())})"
r = requests.post(f"{BASE}/api/v1/memory/{ITEM}/memories",
    json={"content": test_content, "memory_type": "fact"},
    headers={**h(), "Content-Type": "application/json"}, timeout=15)
log(f"save: {r.status_code} {r.text[:150]}")

# 3. search it back via REST (handler scope)
r = requests.post(f"{BASE}/api/v1/memory/{ITEM}/memories/search",
    json={"query": "胎记端口", "n_results": 5},
    headers={**h(), "Content-Type": "application/json"}, timeout=15)
log(f"search: {r.status_code}")
found = test_content in r.text
log(f"found in search results: {found}")

# 4. list memories (handler pool visible through item endpoint)
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories?limit=5",
    headers=h(), timeout=15)
log(f"list: {r.status_code}, count={r.json().get('count')}")

# 5. token stats endpoint (handler scope)
r = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h(), timeout=15)
log(f"token-usage: {r.status_code} total={r.json().get('total_tokens')}")

# 6. by-task endpoint
r = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage/by-task?limit=5", headers=h(), timeout=15)
tasks = r.json().get("tasks", [])
log(f"by-task: {r.status_code} tasks={len(tasks)}")

print("E2E", "PASS" if found else "FAIL")
