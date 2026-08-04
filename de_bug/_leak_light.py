# -*- coding: utf-8 -*-
"""Lightweight leak attribution: torch warmup -> tracemalloc(frames=1) -> 30 pure chats -> diff."""
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
token = None

def login():
    global token
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=30)
    token = r.json()["access_token"]

def malloc_test():
    return requests.get(f"{BASE}/api/v1/utils/malloc-test/", timeout=30).json()

def mem_top():
    return requests.get(f"{BASE}/api/v1/utils/mem-top/?top=10", timeout=120).json()

def tm(action, top=20, frames=1):
    return requests.get(f"{BASE}/api/v1/utils/tracemalloc-ctl/?action={action}&top={top}&frames={frames}", timeout=120).json()

def chat(msg):
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
                          json={"message": msg, "history": []},
                          headers={"Authorization": f"Bearer {token}"}, timeout=240)
        return r.status_code, round(time.time() - t0, 1)
    except Exception as e:
        return 0, str(e)[:80]

login()

print("=== STEP 1: torch warmup chat ===", flush=True)
s, el = chat("你好呀小柴")
print(f"warmup chat -> status={s} {el}s", flush=True)
d = malloc_test()
print(f"after warmup: rss={d['rss_before_mb']}MB threads={d['threads']} used={d['mallinfo']['used_mb']}MB", flush=True)

print("\n=== STEP 2: mem-top baseline ===", flush=True)
m0 = mem_top()
print(f"rss={m0['rss_mb']}MB gc_objects={m0['gc_objects']}", flush=True)
for t in m0["top_types_by_total"][:8]:
    print(f"  {t['type']:<22}{t['count']:>9}{t['total_kb']:>11} kB", flush=True)

print("\n=== STEP 3: tracemalloc start (frames=1) ===", flush=True)
print(tm("start", frames=1), flush=True)

print("\n=== STEP 4: 30 pure conversational chats ===", flush=True)
msgs = ["今天心情不错呀", "你吃饭了吗", "给我讲个冷笑话", "最近天气真好",
        "你喜欢什么颜色", "陪我聊聊天吧", "你会唱歌吗", "早上好呀"]
t0 = time.time()
for i in range(30):
    s, el = chat(msgs[i % len(msgs)])
    if i % 10 == 9:
        d = malloc_test()
        print(f"  [{i+1}/30] status={s} {el}s | rss={d['rss_before_mb']}MB threads={d['threads']}", flush=True)
print(f"done in {round(time.time()-t0)}s", flush=True)

print("\n=== STEP 5: tracemalloc top growth (vs step3 baseline) ===", flush=True)
res = tm("top", 25)
print(f"rss={res.get('rss_mb')}MB", flush=True)
for g in res.get("top_growth", []):
    print(f"  +{g['diff_kb']:>9} kB  {g['location'][:160]}", flush=True)

print("\n=== STEP 6: mem-top after ===", flush=True)
m1 = mem_top()
print(f"rss={m1['rss_mb']}MB gc_objects={m1['gc_objects']} (was {m0['gc_objects']})", flush=True)
for t in m1["top_types_by_total"][:8]:
    print(f"  {t['type']:<22}{t['count']:>9}{t['total_kb']:>11} kB", flush=True)
d = malloc_test()
print(f"final: rss={d['rss_before_mb']}MB used={d['mallinfo']['used_mb']}MB frag={d['mallinfo']['frag_pct']}% threads={d['threads']}", flush=True)
print("\n[DONE]", flush=True)