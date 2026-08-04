import json, sqlite3

db = r"backend\.runtime\agent_state.db"
con = sqlite3.connect(db)
cur = con.cursor()
rows = cur.execute("SELECT ticket_id, status, updated_at, payload FROM agent_ticket_state").fetchall()
print(f"total tickets: {len(rows)}")
stuck = []
for ticket_id, status, updated_at, payload in rows:
    data = json.loads(payload or "{}")
    req = str(data.get("request_message") or "")[:50]
    print(f"[{status:10}] {updated_at} req={req!r} id={ticket_id}")
    if status in {"running", "pending", "sending"}:
        stuck.append(ticket_id)

for ticket_id in stuck:
    row = cur.execute("SELECT payload FROM agent_ticket_state WHERE ticket_id=?", (ticket_id,)).fetchone()
    data = json.loads(row[0])
    data["status"] = "completed"
    cur.execute(
        "UPDATE agent_ticket_state SET status='completed', payload=? WHERE ticket_id=?",
        (json.dumps(data, ensure_ascii=False), ticket_id),
    )
    print(f"finalized stuck ticket {ticket_id}")
con.commit()
con.close()
print("done")
