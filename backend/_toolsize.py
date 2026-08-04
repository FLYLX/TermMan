import json, asyncio
from sqlmodel import Session, select
from app.core.db import engine
from app.models import ItemHandler, ItemHandlerItem
from app.services.agent.agent import Agent

with Session(engine) as session:
    link = session.exec(select(ItemHandlerItem).where(ItemHandlerItem.item_id == "ea52de0c-51b7-4b49-a43d-985ed2e09579")).first()
    handler = session.get(ItemHandler, link.item_handler_id)

agent = Agent.from_handler(handler, instance_key="measure2")
asyncio.run(agent.start_mcp_servers())
tools = agent.get_tools_for_litellm()
rows = []
for t in tools:
    name = t["function"]["name"]
    size = len(json.dumps(t, ensure_ascii=False))
    rows.append((size, name))
rows.sort(reverse=True)
total = sum(s for s, _ in rows)
print(f"TOTAL {len(rows)} tools, {total} chars, ~{total//4} tokens")
for size, name in rows:
    print(f"{size:6d} (~{size//4:4d} tok) {name}")