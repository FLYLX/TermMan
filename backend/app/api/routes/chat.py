import asyncio
import json
import logging
import queue
import re
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from litellm import completion
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep
from app.models import ItemHandler
from app.services.agent.agent import agent_manager
from app.services.agent.chat_runtime import (
    get_item_handler_llm_config,
    prepare_chat_agent,
)
from app.services.agent.history.chat import (
    append_chat_message,
    get_previous_assistant_response_before_latest_user_message,
)
from app.services.agent.integrations import (
    extract_integration_context_targets,
    fallback_is_delivery_result,
    get_delivery_retry_decision,
    record_integration_context_targets,
    record_integration_delivery_correction,
)
from app.services.agent.memory.vector_store import vector_store
from app.services.agent.prompts.builder import build_chat_turn_messages
from app.services.agent.prompts.policy import (
    build_confirmation_memory_candidate,
    build_conversation_memory_candidate,
    build_status_update_memory_candidate,
    persist_memory_candidate,
)
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.session import agent_session_manager
from app.services.agent.stream_manager import stream_manager
from app.services.agent.tool_grounding import guard_ungrounded_tool_claim

if TYPE_CHECKING:
    from app.services.agent.agent import Agent

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1
REQUEST_TIMEOUT = 120
MAX_ITERATIONS = 10
LOOP_DETECTION_WINDOW = 6
LOOP_THRESHOLD = 3
SILENT_TOOL_NAMES = {"mcp_local_read_terminal_log", "mcp_robot_send_message"}
HIDDEN_TOOL_RESULT_NAMES = {"mcp_robot_send_message"}
AUTO_TASK_SOURCE = "agent_plan"
AUTO_TASK_TTL_DAYS = 7
MAX_AUTO_TASKS = 5

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


@dataclass
class PlannedTask:
    memory_id: str
    order: int


@dataclass
class PlannedTaskRuntime:
    request_id: str
    tasks: list[PlannedTask]
    current_index: int = 0
    tool_started: bool = False
    tool_finished: bool = False


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
            if skill.category in {"system", "persona"}:
                continue
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



def _has_active_robot_chat_context(agent: Any) -> bool:
    context = getattr(agent, "_context", None)
    return bool(str(getattr(context, "robot_id", "") or "").strip())


def _run_async_from_sync(coro_factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def runner():
        try:
            result_queue.put((True, asyncio.run(coro_factory())))
        except BaseException as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    ok, result = result_queue.get()
    if ok:
        return result
    raise result


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


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _extract_json_payload(raw_content: str) -> Any | None:
    candidates: list[str] = []
    normalized = (raw_content or "").strip()
    if not normalized:
        return None

    candidates.append(normalized)
    if normalized.startswith("```"):
        fenced = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.IGNORECASE)
        fenced = re.sub(r"\s*```$", "", fenced)
        candidates.append(fenced.strip())

    first_object = normalized.find("{")
    last_object = normalized.rfind("}")
    if first_object != -1 and last_object > first_object:
        candidates.append(normalized[first_object : last_object + 1])

    first_array = normalized.find("[")
    last_array = normalized.rfind("]")
    if first_array != -1 and last_array > first_array:
        candidates.append(normalized[first_array : last_array + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    return None


def _normalize_task_title(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    normalized = value.strip()
    normalized = re.sub(
        r"^\s*(?:task|任务)?\s*\d+\s*[:：.\-、)]\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"^\s*[-*]\s*", "", normalized)
    return normalized.strip()[:120]


def _parse_task_titles(raw_content: str) -> list[str]:
    payload = _extract_json_payload(raw_content)
    if payload is None:
        return []

    if isinstance(payload, dict):
        entries = (
            payload.get("tasks")
            or payload.get("items")
            or payload.get("plan")
            or payload.get("steps")
            or []
        )
    elif isinstance(payload, list):
        entries = payload
    else:
        entries = []

    titles: list[str] = []
    seen: set[str] = set()

    for entry in entries:
        title = ""
        if isinstance(entry, str):
            title = _normalize_task_title(entry)
        elif isinstance(entry, dict):
            for key in ("title", "task", "name", "content", "summary", "step"):
                candidate = _normalize_task_title(entry.get(key))
                if candidate:
                    title = candidate
                    break

        if not title:
            continue

        fingerprint = title.casefold()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        titles.append(title)

        if len(titles) >= MAX_AUTO_TASKS:
            break

    return titles


def _build_fallback_task_titles(message: str) -> list[str]:
    normalized = (message or "").lower()
    prefers_chinese = _contains_cjk(message)

    if "python" in normalized or ".py" in normalized:
        return (
            ["编写 Python 代码", "执行 Python 脚本", "检查输出是否正确"]
            if prefers_chinese
            else ["Write the Python code", "Run the Python script", "Verify the output"]
        )

    if any(token in normalized for token in ("file", "folder", "目录", "文件")):
        return (
            ["确认目标文件与路径", "执行文件操作", "检查文件结果是否正确"]
            if prefers_chinese
            else ["Confirm the target file and path", "Perform the file operation", "Verify the file result"]
        )

    return (
        ["分析用户请求", "执行所需操作", "检查结果并反馈"]
        if prefers_chinese
        else ["Analyze the request", "Perform the required operation", "Verify the result and report back"]
    )


def _plan_agent_task_titles(
    handler: ItemHandler,
    message: str,
    history: list[ChatMessage],
) -> list[str]:
    prefers_chinese = _contains_cjk(message)
    context_lines = [
        f"{entry.role}: {entry.content.strip()}"
        for entry in history[-4:]
        if entry.content and entry.content.strip()
    ]
    context_block = "\n".join(context_lines).strip()

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are a task planner for a coding and terminal agent. "
                "Break the user's latest request into 2 to 5 concrete execution tasks. "
                "Return only JSON in the format "
                '{"tasks":[{"title":"..."}]}. '
                "Requirements: each task title must be short, actionable, ordered, and reflect actual execution. "
                "The final task should verify the result. "
                "Match the user's language."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Recent context:\n{context_block or '(none)'}\n\n"
                f"Latest request:\n{message.strip()}\n\n"
                "Return JSON only."
            ),
        },
    ]

    try:
        kwargs = _build_completion_kwargs(
            handler,
            messages=prompt_messages,
            tools=[],
            stream=False,
        )
        kwargs["max_tokens"] = 300
        response = completion(**kwargs)
        raw_content = (
            response.choices[0].message.content
            if response and getattr(response, "choices", None)
            else ""
        )
        titles = _parse_task_titles(raw_content or "")
        if titles:
            return titles
        logger.warning("[Chat] Auto task planner returned no valid tasks for item handler %s", handler.id)
    except Exception as exc:
        logger.warning("[Chat] Auto task planner failed for handler %s: %s", handler.id, exc)

    fallback_titles = _build_fallback_task_titles(message)
    if prefers_chinese and len(fallback_titles) < 2:
        return ["分析用户请求", "执行所需操作", "检查结果并反馈"]
    if not prefers_chinese and len(fallback_titles) < 2:
        return ["Analyze the request", "Perform the required operation", "Verify the result and report back"]
    return fallback_titles


def _clear_existing_agent_plan_tasks(item_id: str) -> None:
    try:
        memories = vector_store.get_all_memories(item_id, memory_type="task")
    except Exception as exc:
        logger.warning("[Chat] Failed to load existing task plan memories for item %s: %s", item_id, exc)
        return

    for memory in memories:
        metadata = memory.get("metadata") or {}
        if metadata.get("source") != AUTO_TASK_SOURCE:
            continue
        try:
            vector_store.delete_memory(memory["id"])
        except Exception as exc:
            logger.warning("[Chat] Failed to delete stale task plan memory %s: %s", memory.get("id"), exc)


def _update_agent_plan_memory(
    memory_id: str,
    *,
    status: str | None = None,
    task_state: str | None = None,
) -> None:
    memory = vector_store.get_memory(memory_id)
    if not memory:
        return

    metadata = dict(memory.get("metadata") or {})
    changed = False

    if status and metadata.get("status") != status:
        metadata["status"] = status
        metadata["status_updated_at"] = datetime.now().isoformat()
        changed = True

    if task_state and metadata.get("task_state") != task_state:
        metadata["task_state"] = task_state
        changed = True

    if not changed:
        return

    metadata["source"] = AUTO_TASK_SOURCE
    metadata["type"] = AUTO_TASK_SOURCE
    metadata["verified"] = True
    metadata["updated_at"] = datetime.now().isoformat()

    try:
        vector_store.update_memory(
            memory_id=memory_id,
            content=str(memory.get("content") or ""),
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning("[Chat] Failed to update task plan memory %s: %s", memory_id, exc)


def _advance_agent_task_plan(plan: PlannedTaskRuntime | None, target_index: int) -> None:
    if not plan or not plan.tasks:
        return

    bounded_index = max(0, min(target_index, len(plan.tasks) - 1))
    if bounded_index == plan.current_index:
        return

    for index, task in enumerate(plan.tasks):
        if index < bounded_index:
            _update_agent_plan_memory(task.memory_id, status="completed", task_state="completed")
        elif index == bounded_index:
            _update_agent_plan_memory(task.memory_id, status="active", task_state="running")
        else:
            _update_agent_plan_memory(task.memory_id, status="active", task_state="pending")

    plan.current_index = bounded_index


def _complete_agent_task_plan(plan: PlannedTaskRuntime | None) -> None:
    if not plan:
        return

    for task in plan.tasks:
        _update_agent_plan_memory(task.memory_id, status="completed", task_state="completed")


def _mark_agent_task_plan_failed(plan: PlannedTaskRuntime | None) -> None:
    if not plan or not plan.tasks:
        return

    current_index = max(0, min(plan.current_index, len(plan.tasks) - 1))
    for index, task in enumerate(plan.tasks):
        if index < current_index:
            _update_agent_plan_memory(task.memory_id, status="completed", task_state="completed")
        elif index == current_index:
            _update_agent_plan_memory(task.memory_id, status="active", task_state="failed")
        else:
            _update_agent_plan_memory(task.memory_id, status="active", task_state="pending")


def _create_agent_task_plan(
    item_id: str,
    *,
    handler: ItemHandler,
    message: str,
    history: list[ChatMessage],
    tools: list[dict[str, Any]],
) -> PlannedTaskRuntime | None:
    if not tools:
        return None

    if build_status_update_memory_candidate(item_id, message, store=vector_store) is not None:
        return None

    _clear_existing_agent_plan_tasks(item_id)

    task_titles = _plan_agent_task_titles(handler, message, history)
    if not task_titles:
        return None

    prefers_chinese = _contains_cjk(message)
    request_id = str(uuid4())
    planned_tasks: list[PlannedTask] = []

    for index, title in enumerate(task_titles, start=1):
        content = f"{'任务' if prefers_chinese else 'Task'} {index}{'：' if prefers_chinese else ': '} {title}"
        memory_id = vector_store.add_memory(
            item_id=item_id,
            content=content,
            memory_type="task",
            metadata={
                "source": AUTO_TASK_SOURCE,
                "type": AUTO_TASK_SOURCE,
                "verified": True,
                "status": "active",
                "task_state": "running" if index == 1 else "pending",
                "task_order": index,
                "task_title": title,
                "task_total": len(task_titles),
                "task_request_id": request_id,
            },
            ttl_days=AUTO_TASK_TTL_DAYS,
        )
        if memory_id:
            planned_tasks.append(PlannedTask(memory_id=memory_id, order=index))

    if not planned_tasks:
        return None

    return PlannedTaskRuntime(
        request_id=request_id,
        tasks=planned_tasks,
        current_index=0,
    )


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
    include_hidden_tool_results: bool = False,
) -> Generator[str, None, None]:
    if agent is None:
        agent = agent_manager.get_or_create(handler)

    messages = build_chat_turn_messages(
        agent,
        item_id=item_id,
        message=message,
        query=message,
    )
    extract_integration_context_targets(agent, messages)
    record_integration_context_targets(agent, item_id)
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

    planned_task_runtime = _create_agent_task_plan(
        item_id,
        handler=handler,
        message=message,
        history=history,
        tools=tools,
    )

    tool_call_history: list[tuple[str, str]] = []
    final_response = ""
    tool_called_this_turn = False
    delivery_tool_sent_by_integration = False
    delivery_retry_used_by_integration: dict[str, bool] = {}

    try:
        for _ in range(MAX_ITERATIONS):
            if AgentMessageQueue.is_aborted(item_id):
                _mark_agent_task_plan_failed(planned_task_runtime)
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
                _mark_agent_task_plan_failed(planned_task_runtime)
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
                    _mark_agent_task_plan_failed(planned_task_runtime)
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
                final_response = guard_ungrounded_tool_claim(
                    iteration_content,
                    tool_called=tool_called_this_turn,
                )
                delivery_retry_decision = None
                if not delivery_tool_sent_by_integration:
                    delivery_retry_decision = get_delivery_retry_decision(
                        agent=agent,
                        messages=messages,
                        tools=tools,
                        final_response=final_response,
                        retry_used_by_integration=delivery_retry_used_by_integration,
                    )
                if delivery_retry_decision is not None:
                    record_integration_delivery_correction(
                        agent,
                        integration_name=delivery_retry_decision.integration_name,
                        item_id=item_id,
                        final_response=final_response,
                    )
                    messages.append(delivery_retry_decision.correction_message)
                    continue

                if final_response:
                    if delivery_tool_sent_by_integration and _has_active_robot_chat_context(agent):
                        logger.info(
                            "[Chat] Suppressed final response after robot delivery tool sent for item %s",
                            item_id,
                        )
                        yield _to_sse({"done": True})
                        return

                    _complete_agent_task_plan(planned_task_runtime)
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
            if planned_task_runtime and len(planned_task_runtime.tasks) > 1:
                _advance_agent_task_plan(planned_task_runtime, 1)
                planned_task_runtime.tool_started = True
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
                    _mark_agent_task_plan_failed(planned_task_runtime)
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
                    _mark_agent_task_plan_failed(planned_task_runtime)
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

                result = _run_async_from_sync(
                    lambda tool_name=tool_name, tool_args=tool_args: agent.execute_tool(
                        tool_name,
                        tool_args,
                    )
                )
                tool_called_this_turn = True
                result_text = _format_tool_result(result)
                if result_text and fallback_is_delivery_result(result_text):
                    delivery_tool_sent_by_integration = True

                if result_text:
                    if hide_tool_details:
                        if (
                            include_hidden_tool_results
                            and tool_name in HIDDEN_TOOL_RESULT_NAMES
                        ):
                            yield _to_sse(
                                {
                                    "type": "agent_tool_result",
                                    "content": result_text,
                                    "timestamp": datetime.now().isoformat(),
                                    "tool_name": tool_name,
                                    "hidden": True,
                                }
                            )
                    else:
                        if (
                            planned_task_runtime
                            and not planned_task_runtime.tool_finished
                            and len(planned_task_runtime.tasks) > 2
                        ):
                            _advance_agent_task_plan(planned_task_runtime, 2)
                            planned_task_runtime.tool_finished = True
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
        _mark_agent_task_plan_failed(planned_task_runtime)
        yield _to_sse(warning_event)
        yield _to_sse({"done": True})
    except Exception as exc:
        logger.exception("[Chat] Unexpected stream error for item %s", item_id)
        _mark_agent_task_plan_failed(planned_task_runtime)
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


@router.post("/{item_id}")
async def chat(
    item_id: str,
    request: ChatRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict:
    handler, _, agent = await prepare_chat_agent(session, item_id, current_user)
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
    handler, _, agent = await prepare_chat_agent(session, item_id, current_user)

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
    _, _, agent = await prepare_chat_agent(session, item_id, current_user)
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
