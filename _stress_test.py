import requests, json, time, sys, io, threading
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Rapid fire 5 messages in quick succession
messages = [
    "\u5728MC\u63a7\u5236\u53f0\u6267\u884c list",
    "\u518d\u6267\u884c say stress_test_1",
    "\u518d\u6265\u884c say stress_test_2", 
    "\u67e5\u4e00\u4e0b\u670d\u52a1\u5668 TPS",
    "\u6700\u540e\u6267\u884c say done_all_tests",
]

print("=== RAPID FIRE 5 MESSAGES ===")
for i, msg in enumerate(messages):
    r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", 
        json={"message": msg, "history": []},
        headers=h)
    resp = r2.json().get("content", "")[:80]
    print(f"  [{i+1}] {r2.status_code}: {resp}")
    time.sleep(0.3)  # 300ms between messages

print("\nWaiting 30s for all to process...")
time.sleep(30)

# Check final state
r5 = requests.get(f"{BASE}/api/v1/memory/{ITEM}/session?limit=10&offset=0", headers=h)
hist = r5.json()
msgs = hist if isinstance(hist, list) else hist.get("messages", hist.get("data", []))
print(f"\nSession msgs: {len(msgs)}")
assistant_count = sum(1 for m in msgs if m.get("role") == "assistant")
terminal_count = sum(1 for m in msgs if m.get("role") == "terminal")
print(f"  assistant: {assistant_count}, terminal: {terminal_count}")
print("\nLast 5 messages:")
for m in msgs[-5:]:
    role = m.get("role", "?")
    content = str(m.get("content", ""))[:150]
    print(f"  [{role}] {content}")
