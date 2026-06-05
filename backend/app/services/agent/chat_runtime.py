from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Item, ItemHandler, ItemHandlerItem, User
from app.services.agent.agent import agent_manager, item_handler_context

if TYPE_CHECKING:
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.services.agent.agent import Agent


def get_item_handler_llm_config(
    session: Session,
    item_id: str,
    user: User,
) -> tuple[ItemHandler, Item] | None:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not user.is_superuser and item.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    handler_item = session.exec(
        select(ItemHandlerItem).where(ItemHandlerItem.item_id == item_id)
    ).first()
    if not handler_item:
        return None

    handler = session.get(ItemHandler, handler_item.item_handler_id)
    if not handler:
        return None

    return handler, item


async def prepare_chat_agent(
    session: Session,
    item_id: str,
    current_user: User,
) -> tuple[ItemHandler, Item, Agent]:
    result = get_item_handler_llm_config(session, item_id, current_user)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No ItemHandler associated with this item. Please associate an ItemHandler first.",
        )

    handler, item = result
    if not handler.model:
        raise HTTPException(
            status_code=400,
            detail=f"ItemHandler '{handler.name}' has no model configured.",
        )

    agent = agent_manager.get_or_create(handler)
    agent.set_item_context(item_id, item)
    item_handler_context.set_handler(item_id, str(handler.id))
    await agent.start_mcp_servers()
    return handler, item, agent


async def collect_chat_response(
    *,
    session: Session,
    item_id: str,
    current_user: User,
    message: str,
    history: list[Any] | None = None,
    robot_id: str | None = None,
    robot_sender_key: str | None = None,
    robot_reply_target: RobotReplyTarget | None = None,
) -> str:
    from app.api.routes.chat import generate_stream

    handler, _, agent = await prepare_chat_agent(session, item_id, current_user)

    if robot_id and robot_sender_key and robot_reply_target:
        agent.set_robot_context(
            robot_id=robot_id,
            sender_key=robot_sender_key,
            reply_target=robot_reply_target,
        )
        await agent.ensure_robot_context_tools()

    content = ""
    error_message = ""
    try:
        for chunk in generate_stream(
            message=message,
            history=history or [],
            handler=handler,
            item_id=item_id,
            agent=agent,
        ):
            if not chunk.startswith("data: "):
                continue

            payload = json.loads(chunk[6:].strip())
            if payload.get("type") == "agent_response":
                content = str(payload.get("content") or content)
            elif payload.get("type") in {"agent_error", "error"}:
                error_message = str(payload.get("content") or error_message)
    finally:
        if robot_id:
            agent.clear_robot_context()

    if error_message:
        raise HTTPException(status_code=500, detail=error_message)
    if not content:
        raise HTTPException(
            status_code=502,
            detail="Agent did not return any response content.",
        )
    return content
