import json, urllib.request, urllib.parse

def req(method, url, data=None, headers=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    r = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode())

tok = req("POST", "http://127.0.0.1:28888/api/v1/login/access-token",
          {"username": "admin@example.com", "password": "changethis"},
          {"Content-Type": "application/x-www-form-urlencoded"})["access_token"]
h = {"Authorization": "Bearer " + tok}
item = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

tasks = req("GET", f"http://127.0.0.1:28888/api/v1/items/{item}/token-usage/by-task", None, h)["tasks"]
print("=== last 4 tickets (newest last) ===")
for t in tasks[:4]:
    print(json.dumps({
        "req": t.get("request_message"),
        "src": t.get("source_type"),
        "status": t.get("ticket_status"),
        "turns": t.get("turns"),
        "tokens": t.get("total_tokens"),
        "last_seen": t.get("last_seen"),
        "plan": [p.get("step","")[:20] for p in t.get("plan", [])][:4],
    }, ensure_ascii=False))

print()
print("=== session tail (last 8 msgs, old->new order so print tail) ===")
sess = req("GET", f"http://127.0.0.1:28888/api/v1/memory/{item}/session?limit=100", None, h)
msgs = sess.get("messages") or sess.get("history") or []
if isinstance(sess, list):
    msgs = sess
for m in msgs[-8:]:
    role = m.get("role")
    content = m.get("content")
    if isinstance(content, list):
        content = " ".join(str(c.get("text","")) for c in content if isinstance(c, dict))
    print(f"[{role}] {str(content)[:160]}")
