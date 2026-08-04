# -*- coding: utf-8 -*-
import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
MEM = "224d4990-ccba-4532-96cf-409dfcd137b1"
tok = requests.post(f"{BASE}/api/v1/login/access-token", data={"username":"admin@example.com","password":"changethis"}, timeout=10).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
r = requests.get(f"{BASE}/api/v1/memory/{ITEM}/memories?limit=200", headers=h, timeout=20)
data = r.json()
mems = data.get("memories") if isinstance(data, dict) else data
if isinstance(mems, dict): mems = mems.get("memories", [])
print("total memories:", len(mems or []))
hit = [m for m in (mems or []) if str(m.get("id")) == MEM]
print("dirty memory present:", bool(hit))
task_like = [str(m.get("content"))[:60] for m in (mems or []) if "帮我完成一组任务" in str(m.get("content"))]
print("task-instruction leftovers:", task_like)
