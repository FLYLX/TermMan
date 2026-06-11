from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Item, ItemHandler, ItemHandlerItem, User
from app.services.agent.agent import agent_manager, item_handler_context

if TYPE_CHECKING:
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.services.agent.agent import Agent


@dataclass(frozen=True)
class ChatResponseResult:
    content: str
    robot_message_sent: bool = False


def _is_robot_send_tool_result(value: str) -> bool:
    normalized = value.strip()
    return (
        normalized.startswith("Message sent to QQ ")
        or normalized == "Message sent to current robot conversation."
        or normalized.startswith("Broadcast sent to ")
    )


def _robot_fallback_response_content(
    *,
    robot_id: str | None,
    tool_results: list[str],
    warnings: list[str],
    done_seen: bool,
) -> str:
    if not robot_id:
        return ""

    for result in reversed(tool_results):
        normalized = result.strip()
        if _is_robot_send_tool_result(normalized):
            return normalized

    for result in reversed(tool_results):
        if result.strip():
            return result.strip()

    for warning in reversed(warnings):
        if warning.strip():
            return warning.strip()

    if done_seen:
        return "Agent completed without a final response."
    return ""


def _record_robot_no_final_response(
    robot_id: str | None,
    *,
    fallback_content: str,
    tool_results: list[str],
    warnings: list[str],
) -> None:
    if not robot_id:
        return

    from app.plugins.robot.debug_log import preview_text, record_robot_event

    record_robot_event(
        robot_id,
        direction="agent_internal",
        event="agent_no_final_response",
        message=preview_text(fallback_content),
        payload={
            "tool_result_count": len(tool_results),
            "warning_count": len(warnings),
            "used_fallback": bool(fallback_content),
        },
    )


def _robot_reply_target_is_direct_wakeup(
    robot_reply_target: RobotReplyTarget | None,
) -> bool:
    if robot_reply_target is None:
        return False

    metadata = robot_reply_target.metadata
    return bool(metadata.get("mentioned_bot") or metadata.get("replied_to_bot"))


def _should_send_robot_final_response_fallback(
    *,
    robot_id: str | None,
    robot_reply_target: RobotReplyTarget | None,
    content: str,
    robot_message_sent: bool,
) -> bool:
    return (
        bool(robot_id)
        and robot_reply_target is not None
        and bool(content.strip())
        and not robot_message_sent
        and _robot_reply_target_is_direct_wakeup(robot_reply_target)
    )


def _record_robot_final_response_fallback(
    robot_id: str | None,
    *,
    robot_reply_target: RobotReplyTarget,
    content: str,
) -> None:
    if not robot_id:
        return

    from app.plugins.robot.debug_log import preview_text, record_robot_event

    metadata = robot_reply_target.metadata
    record_robot_event(
        robot_id,
        direction="agent_internal",
        event="agent_final_response_bridge_fallback",
        message=preview_text(content),
        payload={
            "target_type": robot_reply_target.target_type,
            "target_id": robot_reply_target.target_id,
            "mentioned_bot": bool(metadata.get("mentioned_bot")),
            "replied_to_bot": bool(metadata.get("replied_to_bot")),
        },
    )


def _send_robot_final_response_fallback(
    *,
    robot_id: str | None,
    robot_reply_target: RobotReplyTarget | None,
    content: str,
    robot_message_sent: bool,
) -> bool:
    if not _should_send_robot_final_response_fallback(
        robot_id=robot_id,
        robot_reply_target=robot_reply_target,
        content=content,
        robot_message_sent=robot_message_sent,
    ):
        return False

    assert robot_reply_target is not None
    from app.plugins.robot.bridge_client import robot_bridge_client

    text = content.strip()
    _record_robot_final_response_fallback(
        robot_id,
        robot_reply_target=robot_reply_target,
        content=text,
    )
    robot_bridge_client.send_message(robot_id, robot_reply_target, text)
    return True


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
    robot_reply_target: RobotReplyTarget | None = None,
    return_result: bool = False,
) -> str | ChatResponseResult:
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
        ):
            if not chunk.startswith("data: "):
                continue

            payload = json.loads(chunk[6:].strip())
            if payload.get("type") == "agent_response":
                content = str(payload.get("content") or content)
            elif payload.get("type") in {"agent_error", "error"}:
                error_message = str(payload.get("content") or error_message)
            elif payload.get("type") == "agent_tool_result":
                tool_results.append(str(payload.get("content") or ""))
            elif payload.get("type") == "agent_warning":
                warnings.append(str(payload.get("content") or ""))
            elif payload.get("done") is True:
                done_seen = True
    finally:
        if robot_id:
            agent.clear_robot_context()

    if error_message:
        raise HTTPException(status_code=500, detail=error_message)
    robot_message_sent = bool(robot_id) and any(
        _is_robot_send_tool_result(result) for result in tool_results
    )
    if content.strip() and not robot_message_sent:
        robot_message_sent = _send_robot_final_response_fallback(
            robot_id=robot_id,
            robot_reply_target=robot_reply_target,
            content=content,
            robot_message_sent=robot_message_sent,
        )

    if not content:
        fallback_content = _robot_fallback_response_content(
            robot_id=robot_id,
            tool_results=tool_results,
            warnings=warnings,
            done_seen=done_seen,
        )
        if fallback_content:
            _record_robot_no_final_response(
                robot_id,
                fallback_content=fallback_content,
                tool_results=tool_results,
                warnings=warnings,
            )
            result = ChatResponseResult(
                content=fallback_content,
                robot_message_sent=robot_message_sent
                or _is_robot_send_tool_result(fallback_content),
            )
            return result if return_result else result.content
        raise HTTPException(
            status_code=502,
            detail="Agent did not return any response content.",
        )
    result = ChatResponseResult(content=content, robot_message_sent=robot_message_sent)
    return result if return_result else result.content
