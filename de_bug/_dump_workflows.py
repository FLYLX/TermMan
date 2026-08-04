# -*- coding: utf-8 -*-
import json, sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
con = sqlite3.connect(r"backend\.runtime\agent_state.db")
cur = con.cursor()
cols = [r[1] for r in cur.execute("PRAGMA table_info(agent_workflow_state)").fetchall()]
print("columns:", cols)
rows = cur.execute("SELECT * FROM agent_workflow_state").fetchall()
print(f"total workflow rows: {len(rows)}")
for row in rows:
    d = dict(zip(cols, row))
    payload = json.loads(d.get("payload") or "{}")
    print(json.dumps({
        "key": d.get("key"),
        "updated_at": d.get("updated_at"),
        "status": payload.get("status"),
        "reply_ticket_id": payload.get("reply_ticket_id"),
        "reply_ticket_ids": payload.get("reply_ticket_ids"),
        "goal": str(payload.get("goal") or payload.get("request") or payload.get("objective") or "")[:60],
        "steps": [(s.get("title") or s.get("step") or "")[:24] + ":" + str(s.get("status")) for s in (payload.get("steps") or [])][:6],
    }, ensure_ascii=False))
con.close()
