import asyncio
import json
import logging
import queue
import re
import threading
import time
from typing import Any, Generator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from litellm import completion
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Item, ItemHandler, ItemHandlerItem
from app.services.agent import item_handler_context
from app.services.agent.agent import agent_manager
from app.services.agent.chat_history import (
    append_chat_message,
    get_previous_assistant_response_before_latest_user_message,
)
from app.services.agent.memory_policy import (
    build_confirmation_memory_candidate,
    build_conversation_memory_candidate,
    build_status_update_memory_candidate,
    persist_memory_candidate,
)
from app.services.agent.memory.vector_store import vector_store
from app.services.agent.prompt_builder import build_chat_turn_messages
from app.services.agent.prompting import get_system_prompt
from app.services.agent.session import agent_session_manager
from app.services.agent.stream_manager import stream_manager

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1
REQUEST_TIMEOUT = 120
MAX_ITERATIONS = 10
LOOP_DETECTION_WINDOW = 6
LOOP_THRESHOLD = 3
SILENT_TOOL_NAMES = {"mcp_local_read_terminal_log"}

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatStreamRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


def get_item_handler_llm_config(
    session: Session, item_id: str, user: CurrentUser
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


def get_relevant_memories(
    item_id: str,
    query: str,
    agent: "Agent" = None,
    n_results: int = 3,
) -> str:
    if agent:
        skip_tools = agent.get_skip_memory_tools()
        query_lower = query.lower()
        for tool_name in skip_tools:
            tool_base = tool_name.replace("mcp_local_", "").replace("_", " ")
            if tool_base in query_lower:
                logger.info(f"[Chat] Skipping memory search for tool operation: {tool_name}")
                return ""

    try:
        memories = vector_store.search_memories(
            item_id=item_id,
            query=query,
            n_results=n_results,
        )
        if not memories:
            return ""

        return "\n".join([f"- {memory['content']}" for memory in memories])
    except Exception as exc:
        logger.warning(f"[Chat] Failed to retrieve memories: {exc}")
        return ""


def extract_important_info(
    user_msg: str,
    assistant_msg: str,
    *,
    item_id: str | None = None,
    matched_skills: list | None = None,
):
    explicit_candidate = build_conversation_memory_candidate(
        user_msg,
        assistant_msg,
        matched_skills=matched_skills,
    )
    if explicit_candidate is not None:
        return explicit_candidate

    if not item_id:
        return None

    previous_assistant_message = get_previous_assistant_response_before_latest_user_message(
        item_id,
        user_msg,
    )
    confirmation_candidate = build_confirmation_memory_candidate(
        user_msg,
        previous_assistant_message,
        matched_skills=matched_skills,
    )
    if confirmation_candidate is not None:
        return confirmation_candidate

    return build_status_update_memory_candidate(
        item_id,
        user_msg,
        store=vector_store,
        matched_skills=matched_skills,
    )


def build_system_prompt_with_skills(
    handler: ItemHandler,
    message: str,
    agent: "Agent" = None,
    memories: str = "",
) -> tuple[str, list, list[dict]]:
    if agent is None:
        agent = agent_manager.get_or_create(handler)

    all_skills = agent.get_skills()
    matched_skills = agent.match_skills(message)
    tools = agent.get_tools_for_litellm()

    parts = [get_system_prompt(agent)]

    if all_skills:
        parts.append("\n## Your Loaded Skills:\n")
        parts.append(
            "You have the following skills loaded. When user asks about your skills, list them:\n"
        )
        for skill in all_skills:
            parts.append(f"- **{skill.name}** (ID: {skill.skill_id})")
            if skill.description:
                parts.append(f"  Description: {skill.description}")
        parts.append("")

    if matched_skills:
        parts.append("\n## Skills Relevant to Current Query:\n")
        for skill in matched_skills:
            parts.append(f"### {skill.name}")
            if skill.description:
                parts.append(f"Description: {skill.description}")

            if skill.action and skill.action.prompt:
                parts.append(f"\n{skill.action.prompt}\n")

            if skill.content:
                content_without_frontmatter = skill.content
                match = re.match(r"^---\s*\n.*?\n---\s*\n", skill.content, re.DOTALL)
                if match:
                    content_without_frontmatter = skill.content[match.end() :].strip()
                if content_without_frontmatter:
                    parts.append(f"Additional Info:\n{content_without_frontmatter}")
            parts.append("")

    if memories:
        parts.append(f"\n## Relevant Memories:\n{memories}")

    return "\n".join(parts), matched_skills, tools


def _to_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _persist_and_broadcast_event(
    item_id: str,
    *,
    role: str | None,
    content: str,
    message_type: str,
    extra: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    event = append_chat_message(
        item_id,
        role=role,
        content=content,
        message_type=message_type,
        timestamp=timestamp,
        extra=extra,
    )
    stream_manager.broadcast_chat_event(item_id, event)
    return event


def _should_hide_tool_details(tool_name: str) -> bool:
    return tool_name in SILENT_TOOL_NAMES


def _format_tool_result(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("success"):
            result_data = result.get("result", [])
            if isinstance(result_data, list):
                texts = [
                    item.get("text", "")
                    for item in result_data
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                return "\n".join(texts).strip()
            return str(result_data)
        return f"Error: {result.get('error', 'Unknown error')}"

    return str(result)


def _build_completion_kwargs(
    handler: ItemHandler,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict],
    stream: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": handler.model,
        "messages": messages,
        "stream": stream,
        "timeout": REQUEST_TIMEOUT,
        "temperature": 0.1,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if handler.api_key:
        kwargs["api_key"] = handler.api_key
    if handler.api_url:
        kwargs["api_base"] = handler.api_url
    return kwargs


def _append_conversation_memory(
    item_id: str,
    *,
    user_message: str,
    assistant_message: str,
    matched_skills: list,
):
    candidate = extract_important_info(
        user_message,
        assistant_message,
        item_id=item_id,
        matched_skills=matched_skills,
    )
    if not candidate:
        return

    persist_memory_candidate(
        item_id,
        candidate,
        store=vector_store,
    )


def _build_chat_messages(
    *,
    item_id: str,
    message: str,
    history: list[ChatMessage],
    handler: ItemHandler,
    agent: "Agent",
) -> tuple[list[dict[str, Any]], list, list[dict]]:
    memories = get_relevant_memories(item_id, message, agent)
    system_prompt, matched_skills, tools = build_system_prompt_with_skills(
        handler,
        message,
        agent,
        memories,
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": msg.role, "content": msg.content} for msg in history)
    messages.append({"role": "user", "content": message})
    return messages, matched_skills, tools


def _detect_tool_loop(
    tool_call_history: list[tuple[str, str]],
    tool_name: str,
    tool_args_str: str,
) -> tuple[bool, str]:
    tool_call_history.append((tool_name, tool_args_str))
    if len(tool_call_history) > LOOP_DETECTION_WINDOW:
        del tool_call_history[:-LOOP_DETECTION_WINDOW]

    call_counts: dict[tuple[str, str], int] = {}
    for call in tool_call_history:
        call_counts[call] = call_counts.get(call, 0) + 1

    for (repeated_name, _), count in call_counts.items():
        if count >= LOOP_THRESHOLD:
            return True, f"Detected repeated tool loop for {repeated_name} ({count} times)"

    return False, ""


def generate_stream(
    message: str,
    history: list[ChatMessage],
    handler: ItemHandler,
    item_id: str,
    agent: "Agent" = None,
) -> Generator[str, None, None]:
    if agent is None:
        agent = agent_manager.get_or_create(handler)

    messages = build_chat_turn_messages(
        agent,
        item_id=item_id,
        message=message,
        query=message,
    )
    matched_skills = agent.match_skills(message)
    tools = agent.get_tools_for_litellm()

    AgentMessageQueue.clear_abort(item_id)

    user_event = _persist_and_broadcast_event(
        item_id,
        role="user",
        content=message,
        message_type="chat_user",
    )
    yield _to_sse(user_event)

    tool_call_history: list[tuple[str, str]] = []
    final_response = ""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        for _ in range(MAX_ITERATIONS):
            if AgentMessageQueue.is_aborted(item_id):
                warning_event = _persist_and_broadcast_event(
                    item_id,
                    role="assistant",
                    content="Chat aborted",
                    message_type="agent_warning",
                )
                yield _to_sse(warning_event)
                yield _to_sse(
                    {
                        "type": "aborted",
                        "content": warning_event["content"],
                        "timestamp": warning_event["timestamp"],
                    }
                )
                return

            response = None
            last_error: Exception | None = None

            for attempt in range(MAX_RETRIES):
                try:
                    response = completion(
                        **_build_completion_kwargs(
                            handler,
                            messages=messages,
                            tools=tools,
                            stream=True,
                        )
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "[Chat] Stream attempt %s/%s failed for item %s: %s",
                        attempt + 1,
                        MAX_RETRIES,
                        item_id,
                        exc,
                    )
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)

            if response is None:
                error_text = str(last_error or "Unknown stream error")
                error_event = _persist_and_broadcast_event(
                    item_id,
                    role="assistant",
                    content=error_text,
                    message_type="agent_error",
                )
                yield _to_sse(error_event)
                yield _to_sse(
                    {
                        "type": "error",
                        "content": error_text,
                        "timestamp": error_event["timestamp"],
                    }
                )
                return

            iteration_content = ""
            tool_calls_map: dict[int, dict[str, Any]] = {}

            for chunk in response:
                if AgentMessageQueue.is_aborted(item_id):
                    warning_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content="Chat aborted",
                        message_type="agent_warning",
                    )
                    yield _to_sse(warning_event)
                    yield _to_sse(
                        {
                            "type": "aborted",
                            "content": warning_event["content"],
                            "timestamp": warning_event["timestamp"],
                        }
                    )
                    return

                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if not delta:
                    continue

                delta_content = getattr(delta, "content", None)
                if delta_content:
                    iteration_content += delta_content

                delta_tool_calls = getattr(delta, "tool_calls", None)
                if not delta_tool_calls:
                    continue

                for tool_call in delta_tool_calls:
                    index = getattr(tool_call, "index", 0)
                    accumulator = tool_calls_map.setdefault(
                        index,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )

                    tool_call_id = getattr(tool_call, "id", None)
                    if tool_call_id:
                        accumulator["id"] = tool_call_id

                    function = getattr(tool_call, "function", None)
                    if function is None:
                        continue

                    function_name = getattr(function, "name", None)
                    if function_name:
                        accumulator["function"]["name"] += function_name

                    function_arguments = getattr(function, "arguments", None)
                    if function_arguments:
                        accumulator["function"]["arguments"] += function_arguments

            ordered_tool_calls = [
                tool_calls_map[index]
                for index in sorted(tool_calls_map)
                if tool_calls_map[index].get("function", {}).get("name")
            ]

            if not ordered_tool_calls:
                final_response = iteration_content.strip()
                if final_response:
                    response_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content=final_response,
                        message_type="agent_response",
                    )
                    yield _to_sse(response_event)
                    _append_conversation_memory(
                        item_id,
                        user_message=message,
                        assistant_message=final_response,
                        matched_skills=matched_skills,
                    )

                yield _to_sse({"done": True})
                return

            has_visible_tool = any(
                not _should_hide_tool_details(tool_call["function"]["name"])
                for tool_call in ordered_tool_calls
            )
            thinking_text = iteration_content.strip()
            if thinking_text and has_visible_tool:
                thinking_event = _persist_and_broadcast_event(
                    item_id,
                    role="assistant",
                    content=thinking_text,
                    message_type="agent_thinking",
                )
                yield _to_sse(thinking_event)

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": iteration_content,
                "tool_calls": [],
            }
            tool_messages: list[dict[str, Any]] = []

            for tool_call in ordered_tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]
                in_loop, loop_message = _detect_tool_loop(
                    tool_call_history,
                    tool_name,
                    tool_args_str,
                )
                if in_loop:
                    warning_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content=loop_message,
                        message_type="agent_warning",
                        extra={"tool_name": tool_name},
                    )
                    yield _to_sse(warning_event)
                    yield _to_sse({"done": True})
                    return

                try:
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}
                except json.JSONDecodeError:
                    error_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content=f"Failed to parse tool arguments for {tool_name}",
                        message_type="agent_error",
                        extra={"tool_name": tool_name},
                    )
                    yield _to_sse(error_event)
                    yield _to_sse(
                        {
                            "type": "error",
                            "content": error_event["content"],
                            "timestamp": error_event["timestamp"],
                        }
                    )
                    return

                tool_args["item_id"] = item_id
                hide_tool_details = _should_hide_tool_details(tool_name)

                if not hide_tool_details:
                    action_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content=f"Executing tool: {tool_name}",
                        message_type="agent_action",
                        extra={"tool_name": tool_name},
                    )
                    yield _to_sse(action_event)

                result = loop.run_until_complete(agent.execute_tool(tool_name, tool_args))
                result_text = _format_tool_result(result)

                if result_text and not hide_tool_details:
                    result_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content=result_text,
                        message_type="agent_tool_result",
                        extra={"tool_name": tool_name},
                    )
                    yield _to_sse(result_event)

                assistant_message["tool_calls"].append(
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": tool_args_str,
                        },
                    }
                )
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result_text,
                    }
                )

            messages.append(assistant_message)
            messages.extend(tool_messages)

        warning_event = _persist_and_broadcast_event(
            item_id,
            role="assistant",
            content=f"Stopped after reaching the max iteration limit ({MAX_ITERATIONS})",
            message_type="agent_warning",
        )
        yield _to_sse(warning_event)
        yield _to_sse({"done": True})
    except Exception as exc:
        logger.exception("[Chat] Unexpected stream error for item %s", item_id)
        error_event = _persist_and_broadcast_event(
            item_id,
            role="assistant",
            content=str(exc),
            message_type="agent_error",
        )
        yield _to_sse(error_event)
        yield _to_sse(
            {
                "type": "error",
                "content": error_event["content"],
                "timestamp": error_event["timestamp"],
            }
        )
    finally:
        loop.close()


async def _prepare_chat_agent(
    session: Session,
    item_id: str,
    current_user: CurrentUser,
) -> tuple[ItemHandler, Item, "Agent"]:
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


@router.post("/{item_id}")
async def chat(
    item_id: str,
    request: ChatRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict:
    handler, _, agent = await _prepare_chat_agent(session, item_id, current_user)
    matched_skills = agent.match_skills(request.message)

    content = ""
    error_message = ""

    for chunk in generate_stream(
        message=request.message,
        history=request.history,
        handler=handler,
        item_id=item_id,
        agent=agent,
    ):
        if not chunk.startswith("data: "):
            continue

        payload = json.loads(chunk[6:].strip())
        if payload.get("type") == "agent_response":
            content = payload.get("content", content)
        elif payload.get("type") == "agent_error":
            error_message = payload.get("content", error_message)
        elif payload.get("type") == "error":
            error_message = payload.get("content", error_message)

    if error_message:
        raise HTTPException(status_code=500, detail=error_message)

    return {
        "content": content,
        "model": handler.model,
        "matched_skills": [skill.skill_id for skill in matched_skills],
    }


@router.post("/{item_id}/stream")
async def chat_stream(
    item_id: str,
    request: ChatStreamRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    handler, _, agent = await _prepare_chat_agent(session, item_id, current_user)

    return StreamingResponse(
        generate_stream(
            message=request.message,
            history=request.history,
            handler=handler,
            item_id=item_id,
            agent=agent,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{item_id}/skills")
async def get_matched_skills(
    item_id: str,
    query: str,
    session: SessionDep,
    current_user: CurrentUser,
):
    _, _, agent = await _prepare_chat_agent(session, item_id, current_user)
    matched = agent.match_skills(query)
    return {
        "matched_skills": [
            {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
            }
            for skill in matched
        ]
    }


class AgentMessageQueue:
    _abort_flags: dict[str, bool] = {}
    _lock = threading.Lock()

    @classmethod
    def set_abort(cls, item_id: str, abort: bool = True):
        with cls._lock:
            cls._abort_flags[item_id] = abort

    @classmethod
    def is_aborted(cls, item_id: str) -> bool:
        with cls._lock:
            return cls._abort_flags.get(item_id, False)

    @classmethod
    def clear_abort(cls, item_id: str):
        with cls._lock:
            cls._abort_flags.pop(item_id, None)


def _agent_message_callback(item_id: str, msg_queue: queue.Queue):
    def callback(message: dict):
        try:
            msg_queue.put_nowait(message)
        except queue.Full:
            try:
                msg_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                msg_queue.put_nowait(message)
            except queue.Full:
                logger.warning(
                    f"[Chat] Dropping agent event for item {item_id}: subscriber queue full"
                )

    return callback


@router.get("/{item_id}/agent-events")
async def agent_events(
    item_id: str,
    session: SessionDep,
    current_user: CurrentUser,
):
    if not get_item_handler_llm_config(session, item_id, current_user):
        raise HTTPException(status_code=404, detail="No handler found for this item")

    msg_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
    callback = _agent_message_callback(item_id, msg_queue)
    stream_manager.register_chat(item_id, callback)

    def event_generator():
        try:
            while True:
                try:
                    message = msg_queue.get(timeout=30)
                    yield _to_sse(message)
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            stream_manager.unregister_chat(item_id, callback)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{item_id}/abort")
async def abort_chat(
    item_id: str,
    session: SessionDep,
    current_user: CurrentUser,
):
    if not get_item_handler_llm_config(session, item_id, current_user):
        raise HTTPException(status_code=404, detail="No handler found for this item")

    AgentMessageQueue.set_abort(item_id, True)
    stream_manager.reset_session(item_id)

    active_session = agent_session_manager.get_session(item_id)
    if active_session:
        active_session.abort(clear_queue=True)
        active_session.emit_output("本次会话已中断", "agent_warning")
        active_session.emit_status("idle", "")

    return {"success": True, "message": "Chat aborted"}
