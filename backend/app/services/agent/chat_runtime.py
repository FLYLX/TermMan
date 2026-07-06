from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Item, ItemHandler, ItemHandlerItem, User
from app.services.agent.agent import agent_manager, item_handler_context
from app.services.agent.integrations import (
    clear_integration_chat_contexts,
    ensure_integration_chat_context_tools,
    fallback_is_delivery_result,
    integration_fallback_response_content,
    integration_message_sent,
    record_integration_no_final_response,
    send_integration_final_response_fallback,
    setup_integration_chat_contexts,
)

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from app.services.agent.agent import Agent


@dataclass(frozen=True)
class ChatResponseResult:
    content: str
    robot_message_sent: bool = False


def _looks_like_internal_tool_trace(value: str) -> bool:
    from app.plugins.robot.internal_trace import is_robot_internal_trace_text

    return is_robot_internal_trace_text(value)


def _is_integration_internal_response(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    return _looks_like_internal_tool_trace(normalized) or fallback_is_delivery_result(
        normalized
    )


def _sanitize_integration_response(value: str) -> str:
    from app.plugins.robot.internal_trace import sanitize_robot_visible_text

    return sanitize_robot_visible_text(value)


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
    agent.set_user_context(str(current_user.id), bool(current_user.is_superuser))
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
    robot_reply_target: Any | None = None,
    robot_conversation_key: str | None = None,
    robot_conversation_generation: int = 0,
    robot_reply_requires_awake: bool = False,
    return_result: bool = False,
) -> str | ChatResponseResult:
    from app.api.routes.chat import generate_stream

    handler, _, agent = await prepare_chat_agent(session, item_id, current_user)

    integration_contexts: dict[str, dict[str, Any]] = {}
    if robot_id and robot_sender_key and robot_reply_target:
        integration_contexts["robot"] = {
            "robot_id": robot_id,
            "sender_key": robot_sender_key,
            "reply_target": robot_reply_target,
            "conversation_key": robot_conversation_key or "",
            "conversation_generation": robot_conversation_generation,
            "reply_requires_awake": robot_reply_requires_awake,
        }
        setup_integration_chat_contexts(agent, integration_contexts)
        await ensure_integration_chat_context_tools(agent, integration_contexts)

    content = ""
    error_message = ""
    tool_results: list[str] = []
    warnings: list[str] = []
    done_seen = False
    try:
        for chunk in generate_stream(
            message=message,
            history=history or [],
            handler=handler,
            item_id=item_id,
            agent=agent,
            include_hidden_tool_results=True,
            latest_only_context=bool(integration_contexts),
        ):
            if not chunk.startswith("data: "):
                continue

            payload = json.loads(chunk[6:].strip())
            if payload.get("type") == "agent_response":
                candidate = str(payload.get("content") or "")
                if integration_contexts:
                    sanitized_candidate = _sanitize_integration_response(candidate)
                    if _is_integration_internal_response(candidate):
                        tool_results.append(candidate)
                    elif sanitized_candidate:
                        content = sanitized_candidate
                    elif candidate:
                        tool_results.append(candidate)
                elif candidate:
                    content = candidate
            elif payload.get("type") in {"agent_error", "error"}:
                error_message = str(payload.get("content") or error_message)
            elif payload.get("type") == "agent_tool_result":
                tool_results.append(str(payload.get("content") or ""))
            elif payload.get("type") == "agent_warning":
                warnings.append(str(payload.get("content") or ""))
            elif payload.get("done") is True:
                done_seen = True
    finally:
        if integration_contexts:
            clear_integration_chat_contexts(agent, integration_contexts)

    if error_message:
        raise HTTPException(status_code=500, detail=error_message)
    if integration_contexts and _is_integration_internal_response(content):
        tool_results.append(content)
        content = ""
    if integration_contexts and content:
        content = _sanitize_integration_response(content)
    robot_message_sent = bool(integration_contexts) and integration_message_sent(tool_results)
    if robot_message_sent and content.strip():
        logger.info(
            "[ChatRuntime] Suppressed final response after robot delivery tool sent for item %s",
            item_id,
        )
        content = ""
    if content.strip() and not robot_message_sent:
        robot_message_sent = send_integration_final_response_fallback(
            integration_contexts,
            content=content,
            message_sent=robot_message_sent,
        )

    if not content:
        fallback_content = integration_fallback_response_content(
            integration_contexts,
            tool_results=tool_results,
            warnings=warnings,
            done_seen=done_seen,
        )
        if fallback_content:
            record_integration_no_final_response(
                integration_contexts,
                fallback_content=fallback_content,
                tool_results=tool_results,
                warnings=warnings,
            )
            fallback_delivered = fallback_is_delivery_result(fallback_content)
            result = ChatResponseResult(
                content="" if fallback_delivered else fallback_content,
                robot_message_sent=robot_message_sent or fallback_delivered,
            )
            return result if return_result else result.content
        raise HTTPException(
            status_code=502,
            detail="Agent did not return any response content.",
        )
    result = ChatResponseResult(content=content, robot_message_sent=robot_message_sent)
    return result if return_result else result.content
