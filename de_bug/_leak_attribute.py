# -*- coding: utf-8 -*-
"""Leak attribution: torch-load baseline -> tracemalloc start -> 30 chats -> diff."""
import requests, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

def login():
    r = requests.post(f"{BASE}/api/v1/login/access-token",
                      data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
    return r.json()["access_token"]

def malloc_test():
    return requests.get(f"{BASE}/api/v1/utils/malloc-test/", timeout=30).json()

def mem_top():
    return requests.get(f"{BASE}/api/v1/utils/mem-top/?top=12", timeout=120).json()

def tm(action, top=20):
    return requests.get(f"{BASE}/api/v1/utils/tracemalloc-ctl/?action={action}&top={top}", timeout=60).json()

def chat(msg):
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
                          json={"message": msg, "history": []},
                          headers={"Authorization": f"Bearer {token}"}, timeout=180)
        return r.status_code, round(time.time() - t0, 1)
    except Exception as e:
        return 0, str(e)[:80]

token = login()

print("=== STEP 1: trigger torch load via one chat ===", flush=True)
s, el = chat("你好呀小柴，随便聊两句")
print(f"chat1 -> status={s} {el}s", flush=True)
d = malloc_test()
print(f"after chat1: rss={d['rss_before_mb']}MB threads={d['threads']} used={d['mallinfo']['used_mb']}MB frag={d['mallinfo']['frag_pct']}%", flush=True)

print("\n=== STEP 2: baseline mem-top (post-torch state) ===", flush=True)
m0 = mem_top()
print(f"rss={m0['rss_mb']}MB gc_objects={m0['gc_objects']}", flush=True)
for t in m0["top_types_by_total"][:10]:
    print(f"  {t['type']:<24}{t['count']:>9}{t['total_kb']:>11} kB", flush=True)

print("\n=== STEP 3: tracemalloc start ===", flush=True)
print(tm("start"), flush=True)

print("\n=== STEP 4: run 30 chats ===", flush=True)
msgs = ["今天天气怎么样", "给我讲个笑话", "聊聊最近的游戏", "服务器状态如何",
        "帮我看看内存", "随便说点什么", "你在干嘛", "给我唱首歌"]
t0 = time.time()
for i in range(30):
    s, el = chat(msgs[i % len(msgs)] + f" #{i}")
    if i % 10 == 9:
        d = malloc_test()
        print(f"  [{i+1}/30] last status={s} {el}s | rss={d['rss_before_mb']}MB threads={d['threads']}", flush=True)
print(f"30 chats done in {round(time.time()-t0)}s", flush=True)

print("\n=== STEP 5: tracemalloc top growth ===", flush=True)
res = tm("top", 25)
print(f"rss={res.get('rss_mb')}MB", flush=True)
for g in res.get("top_growth", []):
    print(f"  +{g['diff_kb']:>9} kB  {g['location'][:150]}", flush=True)

print("\n=== STEP 6: post-workload mem-top ===", flush=True)
m1 = mem_top()
print(f"rss={m1['rss_mb']}MB gc_objects={m1['gc_objects']} (was {m0['gc_objects']})", flush=True)
for t in m1["top_types_by_total"][:10]:
    print(f"  {t['type']:<24}{t['count']:>9}{t['total_kb']:>11} kB", flush=True)
d = malloc_test()
print(f"final malloc: rss={d['rss_before_mb']}MB used={d['mallinfo']['used_mb']}MB frag={d['mallinfo']['frag_pct']}% threads={d['threads']}", flush=True)
print("\n[DONE]", flush=True)