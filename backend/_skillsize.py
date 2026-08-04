from sqlmodel import Session, select
from app.core.db import engine
from app.models import ItemHandler, ItemHandlerItem
from app.services.agent.agent import Agent
import asyncio

with Session(engine) as session:
    link = session.exec(select(ItemHandlerItem).where(ItemHandlerItem.item_id == "ea52de0c-51b7-4b49-a43d-985ed2e09579")).first()
    handler = session.get(ItemHandler, link.item_handler_id)
    print("handler.enabled_skills:", handler.enabled_skills)

agent = Agent.from_handler(handler, instance_key="measure3")
asyncio.run(agent.start_mcp_servers())
for skill in agent.get_skills():
    action_prompt = skill.action.prompt if skill.action and skill.action.prompt else ""
    content = skill.content or ""
    print(f"{skill.skill_id:32s} cat={skill.category:10s} action_prompt={len(action_prompt):6d} content={len(content):6d} trigger={bool(skill.trigger and skill.trigger.patterns)}")