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
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from litellm import completion
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep
from app.core.tool_markup import extract_dsml_tool_calls
from app.models import Item, ItemHandler
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
from app.services.agent.pending_context import (
    build_pending_terminal_continuation_prompt,
    clear_pending_terminal_continuation,
    record_pending_terminal_continuation,
)
from app.services.agent.prompts.builder import build_chat_turn_messages
from app.services.agent.prompts.policy import (
    build_confirmation_memory_candidate,
    build_conversation_memory_candidate,
    build_status_update_memory_candidate,
    persist_memory_candidate,
)
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.reply_ticket import SOURCE_QQ, SOURCE_WEB, reply_ticket_manager
from app.services.agent.robot_delivery import (
    ROBOT_QQ_REPLY_EVENT_TYPE,
    ROBOT_SEND_TOOL_NAME,
    robot_reply_event_content,
)
from app.services.agent.session import (
    COMMAND_DISPATCH_FAILURE_MESSAGE,
    COMMAND_TOOL_NAMES,
    RUN_JOB_TOOL_NAME,
    agent_session_manager,
    is_background_job_started_result,
    is_command_dispatch_failure_result,
    is_command_dispatch_pending_result,
    is_pending_reply_sent_result,
    is_tool_result_auto_routed_to_job,
    should_auto_route_terminal_tool_to_job,
)
from app.services.agent.stream_manager import stream_manager
from app.services.agent.task_workflow import task_workflow_manager
from app.services.agent.tool_arguments import (
    ToolArgumentParseError,
    parse_tool_arguments,
)
from app.services.agent.tool_grounding import guard_ungrounded_tool_claim
from app.services.agent.tool_selection import select_tools_for_turn
from app.services.agent.turn_coordinator import agent_turn_coordinator, agent_turn_key
from app.services.llm_completion import build_litellm_completion_kwargs

if TYPE_CHECKING:
    from app.services.agent.agent import Agent

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1
REQUEST_TIMEOUT = 120
MAX_ITERATIONS = 10
LOOP_DETECTION_WINDOW = 6
LOOP_THRESHOLD = 3
TOOL_LOOP_STOP_REASON = "任务因重复调用同类工具且没有产生新进展而暂停。"
TOOL_BUDGET_STOP_REASON = "任务在本轮未能收敛，已暂停并保留当前进度。"
SILENT_TOOL_NAMES = {
    "mcp_local_read_terminal_log",
    RUN_JOB_TOOL_NAME,
    "mcp_robot_send_message",
    "mcp_robot_save_memory",
}
HIDDEN_TOOL_RESULT_NAMES = {
    "mcp_robot_send_message",
    "mcp_local_send_pending_reply",
}
BACKGROUND_JOB_RUNNING_RESPONSE = (
    "\u540e\u53f0\u4efb\u52a1\u8fd8\u5728\u8fd0\u884c\uff0c"
    "\u6211\u4e0d\u4f1a\u91cd\u590d\u542f\u52a8\u65b0\u7684\u4e0b\u8f7d/"
    "\u5b89\u88c5/\u6784\u5efa\u4efb\u52a1\uff1b"
    "\u4f60\u53ef\u4ee5\u7ee7\u7eed\u95ee\u522b\u7684\uff0c"
    "\u4efb\u52a1\u5b8c\u6210\u540e\u6211\u4f1a\u56de\u5230\u5bf9\u5e94\u6765\u6e90\u3002"
)
MAX_AUTO_TASKS = 5
INTERNAL_QQ_BACKGROUND_JOB_PREFIX = (
    "[Background terminal job result for this QQ conversation]"
)
TASK_WORKFLOW_REQUEST_RE = re.compile(
    r"(安装|装(?:个|一下|好)?|下载|部署|构建|编译|配置|修改|修复|创建|删除|启动|停止|重启|"
    r"更新|升级|迁移|解压|上传|运行|执行|测试|开服|换源|"
    r"下(?:载|一个|一下)?\s*(?:java|jdk|软件|依赖|包|文件|模组|整合包|服务端)|"
    r"问问|问一下|帮我问|帮忙问|转问|转告后等待|"
    r"\b(?:install|download|deploy|build|compile|configure|modify|fix|create|"
    r"delete|start|stop|restart|update|upgrade|migrate|extract|upload|run|"
    r"execute|test)\b)",
    re.IGNORECASE,
)
TASK_WORKFLOW_CONTINUATION_RE = re.compile(
    r"(继续|接着|重试|再试|换源|换个源|用国内源|好了|好了吗|完了|完了吗|"
    r"完成了吗|结束了吗|成功了吗|失败了吗|进度|怎么样了|怎样了|现在呢|结果呢|"
    r"开了|可以了|那就|然后|下一步|"
    r"\b(?:continue|retry|resume|next|try again)\b)",
    re.IGNORECASE,
)
ROBOT_SEND_FOLLOW_UP_RE = re.compile(
    r"(?:转发|发送|发(?!现|生|布|挥|明|烧|呆|票|热)|通知|告诉|(?:跟|向|对).{0,24}说)",
    re.IGNORECASE,
)
ROBOT_CONTEXT_HISTORY_RE = re.compile(
    r"(?:\[Robot message;|\bQQ\b|QQ群|群里|群号|私聊|转发|发给)",
    re.IGNORECASE,
)
DEFERRED_TASK_RE = re.compile(
    r"(?:安装|下载|构建|编译|部署|升级|等待|后台|定时|任务|问问|转问|"
    r"完成后|结束后|成功后|失败后|收到.+后|等.+后|之后再|"
    r"\b(?:install|download|build|compile|deploy|wait|background|after|when|job)\b)",
    re.IGNORECASE,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def _is_internal_agent_callback(message: str, source_type: str) -> bool:
    return (
        str(source_type or "").strip().lower() == SOURCE_QQ
        and str(message or "").lstrip().startswith(
            INTERNAL_QQ_BACKGROUND_JOB_PREFIX
        )
    )


class ChatMessage(BaseModel):
    role: str
    content: str


def _build_tool_selection_query(
    message: str,
    history: list[ChatMessage | dict[str, Any]],
) -> str:
    current = str(message or "").strip()
    if not current or len(current) > 80 or not ROBOT_SEND_FOLLOW_UP_RE.search(current):
        return current

    recent_parts: list[str] = []
    for entry in history[-6:]:
        raw_content = (
            entry.get("content")
            if isinstance(entry, dict)
            else getattr(entry, "content", "")
        )
        content = str(raw_content or "").strip()
        if content:
            recent_parts.append(content)
    recent_context = "\n".join(recent_parts)
    if not recent_context or not ROBOT_CONTEXT_HISTORY_RE.search(recent_context):
        return current
    return f"{current}\nRecent forwarding context:\n{recent_context}"


def _is_immediate_web_qq_forward_request(
    message: str,
    *,
    source_type: str,
    tools: list[dict[str, Any]],
) -> bool:
    text = str(message or "").strip()
    return bool(
        source_type == SOURCE_WEB
        and ROBOT_SEND_FOLLOW_UP_RE.search(text)
        and not DEFERRED_TASK_RE.search(text)
        and any(
            tool.get("function", {}).get("name") == ROBOT_SEND_TOOL_NAME
            for tool in tools
        )
    )


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatStreamRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


@dataclass
class PlannedTaskRuntime:
    request_id: str
    tool_started: bool = False
    reply_ticket_id: str = ""
    workflow_id: str = ""


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
    tools = select_tools_for_turn(
        agent.get_tools_for_litellm(),
        source="web",
        query=message,
        agent=agent,
    )

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


def _broadcast_agent_status(
    item_id: str,
    status: str,
    content: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "agent_status",
        "status": status,
        "content": content,
        "timestamp": datetime.now().isoformat(),
    }
    if extra:
        event.update(extra)
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


def _current_reply_ticket_id(agent: Any) -> str:
    context = getattr(agent, "_context", None)
    return str(getattr(context, "reply_ticket_id", "") or "").strip()


def _explicit_web_qq_send_requested(message: str, tool_args: dict[str, Any]) -> bool:
    text = str(message or "").lower()
    has_explicit_target = bool(
        str(tool_args.get("target_type") or "").strip()
        and str(tool_args.get("target_id") or "").strip()
    )
    has_context_target = bool(
        str(tool_args.get("reply_to") or tool_args.get("conversation") or "").strip()
    )
    has_target = has_explicit_target or has_context_target
    if not has_target:
        return False
    qq_words = ("qq", "群", "群号", "qq号", "group")
    has_send_intent = bool(ROBOT_SEND_FOLLOW_UP_RE.search(text)) or any(
        word in text for word in ("send", "message")
    )
    return has_send_intent and (
        has_context_target or any(word in text for word in qq_words)
    )


def _ticket_delivery_trace() -> dict[str, Any]:
    return {
        "type": "agent_tool_result",
        "content": "Message sent to current robot conversation.",
        "timestamp": datetime.now().isoformat(),
        "tool_name": "reply_ticket",
        "hidden": True,
    }


def _hidden_blocked_qq_send_trace() -> dict[str, Any]:
    return {
        "type": "agent_tool_result",
        "content": "Blocked accidental QQ send from non-QQ source.",
        "timestamp": datetime.now().isoformat(),
        "tool_name": ROBOT_SEND_TOOL_NAME,
        "hidden": True,
    }


def _deliver_reply_ticket_final_response(
    *,
    agent: Any,
    item_id: str,
    content: str,
    include_hidden_tool_results: bool,
    reply_ticket_id: str = "",
) -> list[dict[str, Any]]:
    from app.plugins.robot.internal_trace import sanitize_robot_visible_text

    ticket_id = str(reply_ticket_id or "").strip() or _current_reply_ticket_id(agent)
    ticket = reply_ticket_manager.get(ticket_id)
    if not ticket or ticket.source_type != SOURCE_QQ:
        return []
    visible_content = sanitize_robot_visible_text(content).strip()
    if not visible_content:
        return []
    if not reply_ticket_manager.deliver(ticket_id, visible_content):
        return []
    events: list[dict[str, Any]] = [
        _persist_and_broadcast_event(
            item_id,
            role="assistant",
            content=f"已回复 QQ：{visible_content}",
            message_type=ROBOT_QQ_REPLY_EVENT_TYPE,
            extra={"tool_name": "reply_ticket", "qq_delivery": True},
        )
    ]
    if include_hidden_tool_results:
        events.append(_ticket_delivery_trace())
    return events


def _complete_confirmed_external_delivery(ticket_id: str) -> bool:
    can_finalize, _ = task_workflow_manager.can_finalize(ticket_id)
    if not can_finalize:
        return False
    ticket = reply_ticket_manager.get(ticket_id)
    if not ticket:
        return True
    if ticket.pending_reply_active:
        return reply_ticket_manager.complete_pending_reply_after_external_delivery(
            ticket_id
        )
    return reply_ticket_manager.mark_delivered(ticket_id)


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
    return build_litellm_completion_kwargs(
        model=handler.model,
        messages=messages,
        stream=stream,
        timeout=REQUEST_TIMEOUT,
        tools=tools,
        tool_choice="auto",
        api_key=handler.api_key,
        api_base=handler.api_url,
        model_parameters=getattr(handler, "model_parameters", {}),
        default_parameters={"temperature": 0.1},
    )


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


def _current_task_origin(agent: "Agent") -> dict[str, str]:
    context = getattr(agent, "_context", None)
    robot_id = str(getattr(context, "robot_id", "") or "").strip()
    robot_conversation_key = str(
        getattr(context, "robot_conversation_key", "") or ""
    ).strip()
    if robot_id:
        label = robot_conversation_key or "current QQ conversation"
        return {
            "type": "qq",
            "label": f"QQ {label}",
            "reply_rule": "reply through the locked current QQ robot context",
        }
    return {
        "type": "web",
        "label": "TermMan web chat",
        "reply_rule": "reply in the current web chat response",
    }


def _complete_agent_task_plan(plan: PlannedTaskRuntime | None) -> None:
    if not plan:
        return

    workflow = task_workflow_manager.get(plan.workflow_id)
    if workflow and workflow.status not in {
        "ready_to_report",
        "completed",
        "cancelled",
    }:
        return

    if plan.reply_ticket_id:
        reply_ticket_manager.mark_completed(plan.reply_ticket_id)


def _mark_agent_task_plan_failed(
    plan: PlannedTaskRuntime | None,
    reason: str = "Agent turn stopped before the main objective was completed.",
) -> None:
    if not plan:
        return

    if plan.reply_ticket_id and plan.workflow_id:
        task_workflow_manager.update(
            plan.reply_ticket_id,
            action="mark_blocked",
            note=reason,
        )

    if plan.reply_ticket_id:
        reply_ticket_manager.mark_failed(plan.reply_ticket_id, reason)


def _should_create_task_workflow(message: str, tools: list[dict[str, Any]]) -> bool:
    if not tools:
        return False
    text = str(message or "")
    return bool(
        TASK_WORKFLOW_REQUEST_RE.search(text)
        or TASK_WORKFLOW_CONTINUATION_RE.search(text)
    )


def _create_agent_task_plan(
    item_id: str,
    *,
    handler: ItemHandler,
    agent: "Agent",
    message: str,
    history: list[ChatMessage],
    tools: list[dict[str, Any]],
    reply_ticket_id: str = "",
) -> PlannedTaskRuntime | None:
    if not _should_create_task_workflow(message, tools):
        return None

    if build_status_update_memory_candidate(item_id, message, store=vector_store) is not None:
        return None

    locked_reply_ticket_id = str(reply_ticket_id or "").strip()
    if not locked_reply_ticket_id:
        locked_reply_ticket_id = _current_reply_ticket_id(agent)
    reply_ticket = reply_ticket_manager.get(locked_reply_ticket_id)
    origin = _current_task_origin(agent)
    source_type = reply_ticket.source_type if reply_ticket else origin["type"]
    source_label = reply_ticket.source_label if reply_ticket else origin["label"]
    resumable = task_workflow_manager.find_resumable(
        item_id=item_id,
        source_type=source_type,
        source_label=source_label,
    )
    if resumable and TASK_WORKFLOW_CONTINUATION_RE.search(message):
        previous_ticket_id = resumable.reply_ticket_id
        task_workflow_manager.attach_ticket(
            resumable.workflow_id,
            locked_reply_ticket_id,
        )
        reply_ticket_manager.rebind_pending_reply(
            previous_ticket_id,
            locked_reply_ticket_id,
        )
        task_workflow_manager.update(
            locked_reply_ticket_id,
            action="resume",
            note=f"User follow-up: {message.strip()[:500]}",
        )
        return PlannedTaskRuntime(
            request_id=resumable.workflow_id,
            workflow_id=resumable.workflow_id,
        )
    if not TASK_WORKFLOW_REQUEST_RE.search(message):
        return None

    task_titles = _plan_agent_task_titles(handler, message, history)
    if not task_titles:
        return None

    request_id = str(uuid4())

    workflow = task_workflow_manager.create(
        item_id=item_id,
        handler_id=str(handler.id),
        reply_ticket_id=locked_reply_ticket_id,
        objective=message,
        source_type=source_type,
        source_label=source_label,
        step_titles=task_titles,
        workflow_id=request_id,
    )
    if reply_ticket is not None:
        reply_ticket_manager.upsert_pending_reply(
            reply_ticket.ticket_id,
            request_summary=message,
            task_plan=task_titles,
            status="working",
        )
    return PlannedTaskRuntime(
        request_id=request_id,
        workflow_id=workflow.workflow_id,
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
    _inject_active_jobs_prompt_context(item_id, messages)
    return messages, matched_skills, tools


def _inject_active_jobs_prompt_context(
    item_id: str,
    messages: list[dict[str, Any]],
) -> None:
    terminal_session = agent_session_manager.get_session(item_id)
    if not terminal_session:
        return
    terminal_session.inject_active_jobs_prompt_context(messages)


def _detect_tool_loop(
    tool_call_history: list[tuple[str, str]],
    tool_name: str,
    tool_args_str: str,
) -> tuple[bool, str]:
    tool_fingerprint = _tool_loop_fingerprint(tool_name, tool_args_str)
    tool_call_history.append((tool_name, tool_fingerprint))
    if len(tool_call_history) > LOOP_DETECTION_WINDOW:
        del tool_call_history[:-LOOP_DETECTION_WINDOW]

    call_counts: dict[tuple[str, str], int] = {}
    for call in tool_call_history:
        call_counts[call] = call_counts.get(call, 0) + 1

    for (repeated_name, _), count in call_counts.items():
        if count >= LOOP_THRESHOLD:
            return True, f"Detected repeated tool loop for {repeated_name} ({count} times)"

    return False, ""


def _tool_loop_fingerprint(tool_name: str, tool_args_str: str) -> str:
    try:
        payload = json.loads(tool_args_str or "{}")
    except json.JSONDecodeError:
        return " ".join(str(tool_args_str or "").split())

    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    normalized = dict(payload)
    normalized.pop("item_id", None)
    normalized.pop("_reply_ticket_id", None)

    if tool_name == "mcp_local_update_task_workflow":
        # Notes are descriptive and often vary even when the model repeats the
        # same state transition without making progress.
        normalized = {
            key: normalized.get(key)
            for key in ("action", "step_index", "title")
            if normalized.get(key) not in (None, "")
        }

    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sanitize_model_error(reason: str) -> str:
    detail = re.sub(
        r"^Agent request failed:\s*",
        "",
        str(reason or "").strip(),
        flags=re.IGNORECASE,
    )
    detail = re.sub(
        r"(?i)\bbearer\s+[a-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        detail,
    )
    detail = re.sub(
        r"(?i)\bsk-[a-z0-9_-]{8,}\b",
        "[REDACTED]",
        detail,
    )
    detail = re.sub(
        r"(?i)\b(api[_-]?key|authorization)\s*[:=]\s*['\"]?[^,\s'\"}]+",
        r"\1=[REDACTED]",
        detail,
    )
    return re.sub(r"\s+", " ", detail).strip()[:1200]


def _stopped_turn_fallback(reason: str, *, prefers_chinese: bool) -> str:
    normalized_reason = str(reason or "").casefold()
    error_detail = _sanitize_model_error(reason)
    if "unsupportedparamserror" in normalized_reason or (
        "temperature" in normalized_reason and "support" in normalized_reason
    ):
        return (
            f"模型参数不兼容：{error_detail}"
            if prefers_chinese
            else f"Incompatible model parameters: {error_detail}"
        )
    if "no available channel" in normalized_reason or "serviceunavailable" in normalized_reason:
        return (
            f"模型通道不可用：{error_detail}"
            if prefers_chinese
            else f"Model channel unavailable: {error_detail}"
        )
    if any(
        marker in normalized_reason
        for marker in ("authentication", "unauthorized", "invalid api key", "status code: 401")
    ):
        return (
            f"模型接口认证失败：{error_detail}"
            if prefers_chinese
            else f"Model API authentication failed: {error_detail}"
        )
    if "rate limit" in normalized_reason or "status code: 429" in normalized_reason:
        return (
            f"模型接口请求过于频繁：{error_detail}"
            if prefers_chinese
            else f"Model API rate limit reached: {error_detail}"
        )
    if "timeout" in normalized_reason or "timed out" in normalized_reason:
        return (
            f"模型接口响应超时：{error_detail}"
            if prefers_chinese
            else f"Model API timed out: {error_detail}"
        )
    if "agent request failed:" in normalized_reason:
        return (
            f"模型请求失败：{error_detail}"
            if prefers_chinese
            else f"Model request failed: {error_detail}"
        )
    if any(
        marker in normalized_reason
        for marker in ("repeat", "loop", "did not converge", "iteration", "no progress")
    ):
        return (
            "这次操作没有完成，我已停止重复执行。当前进度已保留，请稍后重试。"
            if prefers_chinese
            else "The operation did not complete. I stopped repeating it and kept the current progress. Please retry shortly."
        )
    return (
        "这次操作没有完成。当前进度已保留，请稍后重试。"
        if prefers_chinese
        else "The operation did not complete. The current progress was kept. Please retry shortly."
    )


def _generate_stopped_turn_report(
    handler: ItemHandler,
    messages: list[dict[str, Any]],
    *,
    reason: str,
    prefers_chinese: bool,
) -> str:
    fallback = _stopped_turn_fallback(reason, prefers_chinese=prefers_chinese)
    if str(reason or "").casefold().startswith("agent request failed:"):
        return fallback
    final_messages = [*messages]
    final_messages.append(
        {
            "role": "system",
            "content": (
                "Tool execution is now disabled because this turn did not converge. "
                f"Internal stop reason: {reason} "
                "Give the user one concise final status in the user's language. Summarize only "
                "confirmed results already present in the conversation, clearly say whether the "
                "main objective remains incomplete, and mention at most one useful next action. "
                "Do not call tools. Do not mention iteration limits, MCP, reply tickets, internal "
                "workflows, or tool-loop detection."
            ),
        }
    )
    try:
        kwargs = _build_completion_kwargs(
            handler,
            messages=final_messages,
            tools=[],
            stream=False,
        )
        kwargs["max_tokens"] = 300
        response = completion(**kwargs)
        content = (
            response.choices[0].message.content
            if response and getattr(response, "choices", None)
            else ""
        )
        return str(content or "").strip() or fallback
    except Exception as exc:
        logger.warning("[Chat] Failed to generate stopped-turn report: %s", exc)
        return fallback


def _finalize_stopped_turn(
    *,
    agent: Any,
    handler: ItemHandler,
    item_id: str,
    messages: list[dict[str, Any]],
    planned_task_runtime: PlannedTaskRuntime | None,
    reason: str,
    prefers_chinese: bool,
    include_hidden_tool_results: bool,
    reply_ticket_id: str = "",
) -> list[dict[str, Any]]:
    from app.plugins.robot.internal_trace import sanitize_robot_visible_text

    _mark_agent_task_plan_failed(planned_task_runtime, reason)
    report = _generate_stopped_turn_report(
        handler,
        messages,
        reason=reason,
        prefers_chinese=prefers_chinese,
    )
    visible_report = sanitize_robot_visible_text(report).strip()
    final_report = visible_report or "任务未能完成，已停止处理。"

    ticket_id = str(reply_ticket_id or "").strip() or _current_reply_ticket_id(agent)
    ticket = reply_ticket_manager.get(ticket_id)
    if ticket and ticket.pending_reply_active:
        task_workflow_manager.update(
            ticket_id,
            action="mark_blocked",
            note=str(reason or final_report)[:2000],
        )
        reply_ticket_manager.mark_failed(ticket_id, reason or final_report)
    delivered = False
    if ticket and ticket.source_type == SOURCE_QQ:
        if ticket.pending_reply_active:
            delivered, _ = reply_ticket_manager.send_pending_reply(
                ticket_id,
                final_report,
            )
        else:
            delivered = reply_ticket_manager.deliver(ticket_id, final_report)
        if delivered:
            events = [
                _persist_and_broadcast_event(
                    item_id,
                    role="assistant",
                    content=f"已回复 QQ：{final_report}",
                    message_type=ROBOT_QQ_REPLY_EVENT_TYPE,
                    extra={"tool_name": "reply_ticket", "qq_delivery": True},
                )
            ]
            if include_hidden_tool_results:
                events.append(_ticket_delivery_trace())
            return events

    if ticket and ticket.source_type != SOURCE_QQ:
        if ticket.pending_reply_active:
            reply_ticket_manager.complete_pending_reply_after_external_delivery(
                ticket_id
            )
        else:
            reply_ticket_manager.mark_delivered(ticket_id)
    return [
        _persist_and_broadcast_event(
            item_id,
            role="assistant",
            content=final_report,
            message_type="agent_response",
        )
    ]


def _generate_stream_unserialized(
    message: str,
    history: list[ChatMessage],
    handler: ItemHandler,
    item_id: str,
    agent: "Agent" = None,
    include_hidden_tool_results: bool = False,
    latest_only_context: bool = False,
    source_type: str = SOURCE_WEB,
    reply_ticket_id: str = "",
) -> Generator[str, None, None]:
    if agent is None:
        agent = agent_manager.get_or_create(handler)

    normalized_source_type = str(source_type or SOURCE_WEB).strip().lower()
    internal_agent_callback = _is_internal_agent_callback(
        message,
        normalized_source_type,
    )
    if normalized_source_type == SOURCE_WEB:
        clear_robot_context = getattr(agent, "clear_robot_context", None)
        if callable(clear_robot_context):
            clear_robot_context()

    reply_ticket = reply_ticket_manager.get(reply_ticket_id)
    if (
        reply_ticket is None
        or reply_ticket.item_id != str(item_id)
        or reply_ticket.status == "delivered"
    ):
        reply_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id=item_id,
            handler_id=str(handler.id),
            message=message,
            source_type=normalized_source_type,
        )
    else:
        reply_ticket_manager.attach_to_agent(agent, reply_ticket.ticket_id)
    matched_skills = agent.match_skills(message)
    tool_selection_query = _build_tool_selection_query(message, history)
    tools = select_tools_for_turn(
        agent.get_tools_for_litellm(),
        source="qq" if normalized_source_type == SOURCE_QQ else "web",
        query=tool_selection_query,
        agent=agent,
        reply_ticket_id=reply_ticket.ticket_id,
    )

    planned_task_runtime = None
    if not internal_agent_callback:
        planned_task_runtime = _create_agent_task_plan(
            item_id,
            handler=handler,
            agent=agent,
            message=message,
            history=history,
            tools=tools,
            reply_ticket_id=reply_ticket.ticket_id,
        )
    if planned_task_runtime:
        planned_task_runtime.reply_ticket_id = reply_ticket.ticket_id
        reply_ticket_manager.mark_task_plan(
            reply_ticket.ticket_id,
            planned_task_runtime.request_id,
        )
        tools = select_tools_for_turn(
            agent.get_tools_for_litellm(),
            source="qq" if normalized_source_type == SOURCE_QQ else "web",
            query=tool_selection_query,
            agent=agent,
            reply_ticket_id=reply_ticket.ticket_id,
        )

    agent_context = getattr(agent, "_context", None)
    immediate_web_qq_forward = _is_immediate_web_qq_forward_request(
        message,
        source_type=normalized_source_type,
        tools=tools,
    )
    if agent_context is not None:
        agent_context.robot_backend_target_resolution_enabled = bool(
            normalized_source_type == SOURCE_WEB
            and ROBOT_SEND_FOLLOW_UP_RE.search(str(message or ""))
            and any(
                tool.get("function", {}).get("name") == ROBOT_SEND_TOOL_NAME
                for tool in tools
            )
        )

    pending_context = build_pending_terminal_continuation_prompt(item_id, message)
    messages = build_chat_turn_messages(
        agent,
        item_id=item_id,
        message=message,
        query=message,
        latest_only_context=latest_only_context,
        pending_context=pending_context,
    )
    reply_ticket_prompt = reply_ticket_manager.build_prompt(reply_ticket.ticket_id)
    if reply_ticket_prompt:
        messages.insert(1, {"role": "system", "content": reply_ticket_prompt})
    _inject_active_jobs_prompt_context(item_id, messages)
    extract_integration_context_targets(agent, messages)
    record_integration_context_targets(agent, item_id)

    AgentMessageQueue.clear_abort(item_id)

    if not internal_agent_callback:
        user_event = _persist_and_broadcast_event(
            item_id,
            role="user",
            content=message,
            message_type="chat_user",
        )
        yield _to_sse(user_event)

    tool_call_history: list[tuple[str, str]] = []
    final_response = ""
    tool_called_this_turn = False
    delivery_tool_sent_by_integration = False
    confirmed_external_delivery_to_qq = False
    delivery_retry_used_by_integration: dict[str, bool] = {}
    pending_reply_delivery_retry_used = False

    try:
        for _ in range(MAX_ITERATIONS):
            if AgentMessageQueue.is_aborted(item_id):
                stopped_events = _finalize_stopped_turn(
                    agent=agent,
                    handler=handler,
                    item_id=item_id,
                    messages=messages,
                    planned_task_runtime=planned_task_runtime,
                    reason="Task was interrupted before completion.",
                    prefers_chinese=_contains_cjk(message),
                    include_hidden_tool_results=include_hidden_tool_results,
                    reply_ticket_id=reply_ticket.ticket_id,
                )
                for stopped_event in stopped_events:
                    yield _to_sse(stopped_event)
                yield _to_sse(
                    {
                        "type": "aborted",
                        "content": "Chat aborted",
                        "timestamp": datetime.now().isoformat(),
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
                stopped_events = _finalize_stopped_turn(
                    agent=agent,
                    handler=handler,
                    item_id=item_id,
                    messages=messages,
                    planned_task_runtime=planned_task_runtime,
                    reason=f"Agent request failed: {error_text}",
                    prefers_chinese=_contains_cjk(message),
                    include_hidden_tool_results=include_hidden_tool_results,
                    reply_ticket_id=reply_ticket.ticket_id,
                )
                for stopped_event in stopped_events:
                    yield _to_sse(stopped_event)
                yield _to_sse({"done": True})
                return

            iteration_content = ""
            tool_calls_map: dict[int, dict[str, Any]] = {}

            for chunk in response:
                if AgentMessageQueue.is_aborted(item_id):
                    stopped_events = _finalize_stopped_turn(
                        agent=agent,
                        handler=handler,
                        item_id=item_id,
                        messages=messages,
                        planned_task_runtime=planned_task_runtime,
                        reason="Task was interrupted before completion.",
                        prefers_chinese=_contains_cjk(message),
                        include_hidden_tool_results=include_hidden_tool_results,
                        reply_ticket_id=reply_ticket.ticket_id,
                    )
                    for stopped_event in stopped_events:
                        yield _to_sse(stopped_event)
                    yield _to_sse(
                        {
                            "type": "aborted",
                            "content": "Chat aborted",
                            "timestamp": datetime.now().isoformat(),
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

            iteration_content, dsml_tool_calls = extract_dsml_tool_calls(
                iteration_content,
                allowed_tool_names={
                    str(tool.get("function", {}).get("name") or "").strip()
                    for tool in tools
                    if str(tool.get("function", {}).get("name") or "").strip()
                },
            )
            ordered_tool_calls = [
                tool_calls_map[index]
                for index in sorted(tool_calls_map)
                if tool_calls_map[index].get("function", {}).get("name")
            ]
            if not ordered_tool_calls:
                ordered_tool_calls = dsml_tool_calls

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
                    can_finalize, workflow_correction = (
                        task_workflow_manager.can_finalize(reply_ticket.ticket_id)
                    )
                    if not can_finalize:
                        messages.append(
                            {"role": "assistant", "content": final_response}
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": workflow_correction,
                            }
                        )
                        final_response = ""
                        continue

                    current_ticket = reply_ticket_manager.get(
                        reply_ticket.ticket_id
                    )
                    if (
                        current_ticket
                        and current_ticket.pending_reply_active
                        and not delivery_tool_sent_by_integration
                    ):
                        if not pending_reply_delivery_retry_used:
                            messages.append(
                                {"role": "assistant", "content": final_response}
                            )
                            messages.append(
                                {
                                    "role": "system",
                                    "content": (
                                        "This task has an active pending-reply queue entry. "
                                        "Do not answer with normal final text. Call "
                                        "mcp_local_write_pending_reply(status=ready) if needed, "
                                        "then mcp_local_send_pending_reply with entry_id="
                                        f"{current_ticket.ticket_id}. The send tool must deliver "
                                        "to the stored destination and remove the entry."
                                    ),
                                }
                            )
                            pending_reply_delivery_retry_used = True
                            final_response = ""
                            continue
                        stopped_events = _finalize_stopped_turn(
                            agent=agent,
                            handler=handler,
                            item_id=item_id,
                            messages=messages,
                            planned_task_runtime=planned_task_runtime,
                            reason=(
                                "Agent did not produce a valid final task report after retry."
                            ),
                            prefers_chinese=_contains_cjk(message),
                            include_hidden_tool_results=include_hidden_tool_results,
                            reply_ticket_id=reply_ticket.ticket_id,
                        )
                        for stopped_event in stopped_events:
                            yield _to_sse(stopped_event)
                        _broadcast_agent_status(item_id, "idle")
                        yield _to_sse({"done": True})
                        return

                    if delivery_tool_sent_by_integration:
                        logger.info(
                            "[Chat] Suppressed final response after source delivery tool sent for item %s",
                            item_id,
                        )
                        _broadcast_agent_status(item_id, "idle")
                        yield _to_sse({"done": True})
                        return

                    _complete_agent_task_plan(planned_task_runtime)
                    ticket_events = _deliver_reply_ticket_final_response(
                        agent=agent,
                        item_id=item_id,
                        content=final_response,
                        include_hidden_tool_results=include_hidden_tool_results,
                        reply_ticket_id=reply_ticket.ticket_id,
                    )
                    if ticket_events:
                        for event in ticket_events:
                            yield _to_sse(event)
                        if not internal_agent_callback:
                            _append_conversation_memory(
                                item_id,
                                user_message=message,
                                assistant_message=final_response,
                                matched_skills=matched_skills,
                            )
                        _broadcast_agent_status(item_id, "idle")
                        yield _to_sse({"done": True})
                        return
                    response_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content=final_response,
                        message_type="agent_response",
                    )
                    yield _to_sse(response_event)
                    if reply_ticket.source_type != SOURCE_QQ:
                        reply_ticket_manager.mark_delivered(reply_ticket.ticket_id)
                    if not internal_agent_callback:
                        _append_conversation_memory(
                            item_id,
                            user_message=message,
                            assistant_message=final_response,
                            matched_skills=matched_skills,
                        )

                _broadcast_agent_status(item_id, "idle")

                yield _to_sse({"done": True})
                return

            has_visible_tool = any(
                not _should_hide_tool_details(tool_call["function"]["name"])
                for tool_call in ordered_tool_calls
            )
            if planned_task_runtime:
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
                    logger.warning(
                        "[Chat] %s item=%s ticket=%s tool=%s",
                        loop_message,
                        item_id,
                        reply_ticket.ticket_id,
                        tool_name,
                    )
                    for event in _finalize_stopped_turn(
                        agent=agent,
                        handler=handler,
                        item_id=item_id,
                        messages=messages,
                        planned_task_runtime=planned_task_runtime,
                        reason=TOOL_LOOP_STOP_REASON,
                        prefers_chinese=_contains_cjk(message),
                        include_hidden_tool_results=include_hidden_tool_results,
                        reply_ticket_id=reply_ticket.ticket_id,
                    ):
                        yield _to_sse(event)
                    _broadcast_agent_status(item_id, "idle")
                    yield _to_sse({"done": True})
                    return

                try:
                    tool_args = parse_tool_arguments(tool_name, tool_args_str)
                except ToolArgumentParseError:
                    logger.warning(
                        "[Chat] Failed to parse tool arguments for %s: %r",
                        tool_name,
                        tool_args_str,
                    )
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

                if (
                    tool_name == ROBOT_SEND_TOOL_NAME
                    and (
                        reply_ticket.source_type == SOURCE_WEB
                        or not _has_active_robot_chat_context(agent)
                    )
                    and not _explicit_web_qq_send_requested(message, tool_args)
                ):
                    _mark_agent_task_plan_failed(planned_task_runtime)
                    logger.info(
                        "[Chat] Blocked accidental QQ send from source=%s item=%s",
                        reply_ticket.source_type,
                        item_id,
                    )
                    if include_hidden_tool_results:
                        yield _to_sse(_hidden_blocked_qq_send_trace())
                    _broadcast_agent_status(item_id, "idle")
                    yield _to_sse({"done": True})
                    return

                normalized_tool_args_str = json.dumps(tool_args, ensure_ascii=False)
                tool_args["item_id"] = item_id
                tool_args["_reply_ticket_id"] = reply_ticket.ticket_id
                terminal_session = None
                if tool_name in COMMAND_TOOL_NAMES or tool_name == RUN_JOB_TOOL_NAME:
                    terminal_session = agent_session_manager.get_or_create_session(
                        item_id,
                        str(handler.id),
                    )
                    terminal_input_error = None
                    if terminal_session.has_interactive_terminal_context():
                        auto_routes_to_job = False
                    else:
                        auto_routes_to_job = should_auto_route_terminal_tool_to_job(
                            tool_name,
                            tool_args,
                        )
                        if (
                            not auto_routes_to_job
                            and tool_name in COMMAND_TOOL_NAMES
                            and terminal_session.should_route_execute_command_to_background_job(
                                str(tool_args.get("command") or ""),
                            )
                        ):
                            auto_routes_to_job = True
                    if not auto_routes_to_job:
                        terminal_input_error = terminal_session.validate_terminal_tool_input(
                            tool_name,
                            tool_args,
                        )
                    if terminal_input_error:
                        if (
                            _has_active_robot_chat_context(agent)
                            and terminal_session.has_running_terminal_job()
                        ):
                            ticket_events = _deliver_reply_ticket_final_response(
                                agent=agent,
                                item_id=item_id,
                                content=BACKGROUND_JOB_RUNNING_RESPONSE,
                                include_hidden_tool_results=include_hidden_tool_results,
                                reply_ticket_id=reply_ticket.ticket_id,
                            )
                            if ticket_events:
                                for event in ticket_events:
                                    yield _to_sse(event)
                            else:
                                response_event = _persist_and_broadcast_event(
                                    item_id,
                                    role="assistant",
                                    content=BACKGROUND_JOB_RUNNING_RESPONSE,
                                    message_type="agent_response",
                                    extra={"tool_name": tool_name},
                                )
                                yield _to_sse(response_event)
                            _broadcast_agent_status(item_id, "idle")
                            yield _to_sse({"done": True})
                            return
                        _mark_agent_task_plan_failed(planned_task_runtime)
                        warning_event = _persist_and_broadcast_event(
                            item_id,
                            role="assistant",
                            content=terminal_input_error,
                            message_type="agent_warning",
                            extra={"tool_name": tool_name},
                        )
                        yield _to_sse(warning_event)
                        _broadcast_agent_status(item_id, "idle")
                        yield _to_sse({"done": True})
                        return

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

                if tool_name != "mcp_local_update_task_workflow":
                    task_workflow_manager.record_tool_call(
                        reply_ticket.ticket_id,
                        tool_name=tool_name,
                        command=str(tool_args.get("command") or ""),
                    )

                pending_write_skipped = bool(
                    immediate_web_qq_forward
                    and tool_name == "mcp_local_write_pending_reply"
                )
                if pending_write_skipped:
                    result = {
                        "success": True,
                        "result": [
                            {
                                "type": "text",
                                "text": (
                                    "Pending reply not created: this is an immediate "
                                    "one-step QQ forward. Call mcp_robot_send_message directly."
                                ),
                            }
                        ],
                    }
                else:
                    result = _run_async_from_sync(
                        lambda tool_name=tool_name, tool_args=tool_args: agent.execute_tool(
                            tool_name,
                            tool_args,
                        )
                    )
                    tool_called_this_turn = True
                result_text = _format_tool_result(result)
                if is_pending_reply_sent_result(result):
                    delivery_tool_sent_by_integration = True
                command_dispatch_failed = is_command_dispatch_failure_result(
                    tool_name,
                    result_text,
                )
                command_dispatch_pending = is_command_dispatch_pending_result(
                    tool_name,
                    result_text,
                )
                complete_pending_after_external_delivery = False
                if result_text and fallback_is_delivery_result(result_text):
                    if tool_name == ROBOT_SEND_TOOL_NAME:
                        confirmed_external_delivery_to_qq = True
                    delivery_is_final, _ = task_workflow_manager.can_finalize(
                        reply_ticket.ticket_id
                    )
                    if delivery_is_final:
                        delivery_tool_sent_by_integration = True
                        current_ticket = reply_ticket_manager.get(
                            reply_ticket.ticket_id
                        )
                        complete_pending_after_external_delivery = bool(
                            tool_name == ROBOT_SEND_TOOL_NAME
                            and current_ticket
                            and current_ticket.pending_reply_active
                        )
                        if not complete_pending_after_external_delivery:
                            reply_ticket_manager.mark_delivered(
                                reply_ticket.ticket_id
                            )
                    else:
                        task_workflow_manager.update(
                            reply_ticket.ticket_id,
                            action="record_progress",
                            note="Sent an intermediate status update; the main task remains active.",
                        )
                    if tool_name == ROBOT_SEND_TOOL_NAME:
                        reply_event = _persist_and_broadcast_event(
                            item_id,
                            role="assistant",
                            content=robot_reply_event_content(tool_args, result_text),
                            message_type=ROBOT_QQ_REPLY_EVENT_TYPE,
                            extra={
                                "tool_name": tool_name,
                                "qq_delivery": True,
                            },
                        )
                        if complete_pending_after_external_delivery:
                            reply_ticket_manager.complete_pending_reply_after_external_delivery(
                                reply_ticket.ticket_id
                            )
                        yield _to_sse(reply_event)

                if result_text and not command_dispatch_pending:
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
                        result_event = _persist_and_broadcast_event(
                            item_id,
                            role="assistant",
                            content=result_text,
                            message_type="agent_tool_result",
                            extra={"tool_name": tool_name},
                        )
                        yield _to_sse(result_event)

                if command_dispatch_failed:
                    record_pending_terminal_continuation(
                        item_id=item_id,
                        command=str(tool_args.get("command") or ""),
                        reason="terminal_not_connected",
                        message=COMMAND_DISPATCH_FAILURE_MESSAGE,
                        tool_name=tool_name,
                    )
                    _mark_agent_task_plan_failed(planned_task_runtime)
                    warning_event = _persist_and_broadcast_event(
                        item_id,
                        role="assistant",
                        content=COMMAND_DISPATCH_FAILURE_MESSAGE,
                        message_type="agent_warning",
                        extra={"tool_name": tool_name},
                    )
                    yield _to_sse(warning_event)
                    _broadcast_agent_status(item_id, "idle")
                    yield _to_sse({"done": True})
                    return

                if is_background_job_started_result(result):
                    task_workflow_manager.mark_job_started(
                        reply_ticket.ticket_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    clear_pending_terminal_continuation(
                        item_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    _broadcast_agent_status(item_id, "idle")
                    yield _to_sse({"done": True})
                    return

                if tool_name != "mcp_local_update_task_workflow":
                    tool_success = bool(result.get("success", True)) and not (
                        result_text.strip().lower().startswith("error:")
                    )
                    task_workflow_manager.record_tool_result(
                        reply_ticket.ticket_id,
                        tool_name=tool_name,
                        success=tool_success,
                        result_summary=result_text,
                    )

                if confirmed_external_delivery_to_qq:
                    if _complete_confirmed_external_delivery(
                        reply_ticket.ticket_id
                    ):
                        delivery_tool_sent_by_integration = True

                if (
                    tool_name in COMMAND_TOOL_NAMES
                    and result.get("success")
                    and not is_tool_result_auto_routed_to_job(result)
                ):
                    clear_pending_terminal_continuation(
                        item_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    if terminal_session is None:
                        terminal_session = agent_session_manager.get_or_create_session(
                            item_id,
                            str(handler.id),
                        )
                    terminal_session.mark_terminal_command_dispatched(tool_name, tool_args)
                    waiting_event = _broadcast_agent_status(
                        item_id,
                        "waiting_terminal",
                        "命令已发送，等待终端反馈",
                        {"terminal_source": "raw_feedback", "tool_name": tool_name},
                    )
                    yield _to_sse(waiting_event)
                    yield _to_sse({"done": True})
                    return
                if is_tool_result_auto_routed_to_job(result):
                    clear_pending_terminal_continuation(
                        item_id,
                        command=str(tool_args.get("command") or ""),
                    )
                assistant_message["tool_calls"].append(
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": normalized_tool_args_str,
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

        logger.warning(
            "[Chat] Tool iteration budget exhausted item=%s ticket=%s iterations=%s",
            item_id,
            reply_ticket.ticket_id,
            MAX_ITERATIONS,
        )
        for event in _finalize_stopped_turn(
            agent=agent,
            handler=handler,
            item_id=item_id,
            messages=messages,
            planned_task_runtime=planned_task_runtime,
            reason=TOOL_BUDGET_STOP_REASON,
            prefers_chinese=_contains_cjk(message),
            include_hidden_tool_results=include_hidden_tool_results,
            reply_ticket_id=reply_ticket.ticket_id,
        ):
            yield _to_sse(event)
        _broadcast_agent_status(item_id, "idle")
        yield _to_sse({"done": True})
    except Exception as exc:
        logger.exception("[Chat] Unexpected stream error for item %s", item_id)
        for event in _finalize_stopped_turn(
            agent=agent,
            handler=handler,
            item_id=item_id,
            messages=messages,
            planned_task_runtime=planned_task_runtime,
            reason=f"Unexpected Agent error: {exc}",
            prefers_chinese=_contains_cjk(message),
            include_hidden_tool_results=include_hidden_tool_results,
            reply_ticket_id=reply_ticket.ticket_id,
        ):
            yield _to_sse(event)
        yield _to_sse({"done": True})
    finally:
        reply_ticket_manager.detach_from_agent(agent, reply_ticket.ticket_id)


def generate_stream(
    message: str,
    history: list[ChatMessage],
    handler: ItemHandler,
    item_id: str,
    agent: "Agent" = None,
    include_hidden_tool_results: bool = False,
    latest_only_context: bool = False,
    source_type: str = SOURCE_WEB,
    reply_ticket_id: str = "",
    turn_serialized: bool = False,
) -> Generator[str, None, None]:
    if turn_serialized:
        yield from _generate_stream_unserialized(
            message=message,
            history=history,
            handler=handler,
            item_id=item_id,
            agent=agent,
            include_hidden_tool_results=include_hidden_tool_results,
            latest_only_context=latest_only_context,
            source_type=source_type,
            reply_ticket_id=reply_ticket_id,
        )
        return
    with agent_turn_coordinator.turn(agent_turn_key(str(handler.id))):
        yield from _generate_stream_unserialized(
            message=message,
            history=history,
            handler=handler,
            item_id=item_id,
            agent=agent,
            include_hidden_tool_results=include_hidden_tool_results,
            latest_only_context=latest_only_context,
            source_type=source_type,
            reply_ticket_id=reply_ticket_id,
        )


def _require_chat_handler(
    session: SessionDep,
    item_id: str,
    current_user: CurrentUser,
) -> tuple[ItemHandler, Item]:
    prepared = get_item_handler_llm_config(session, item_id, current_user)
    if not prepared:
        raise HTTPException(
            status_code=404,
            detail="No ItemHandler associated with this item.",
        )
    return prepared


@router.post("/{item_id}")
async def chat(
    item_id: str,
    request: ChatRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict:
    prepared = _require_chat_handler(session, item_id, current_user)
    lease = await agent_turn_coordinator.acquire_async(
        agent_turn_key(str(prepared[0].id))
    )
    try:
        handler, _, agent = await prepare_chat_agent(
            session,
            item_id,
            current_user,
            prepared=prepared,
        )
        matched_skills = agent.match_skills(request.message)

        content = ""
        error_message = ""

        for chunk in generate_stream(
            message=request.message,
            history=request.history,
            handler=handler,
            item_id=item_id,
            agent=agent,
            turn_serialized=True,
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
    finally:
        lease.release()

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
    prepared = _require_chat_handler(session, item_id, current_user)
    lease = await agent_turn_coordinator.acquire_async(
        agent_turn_key(str(prepared[0].id))
    )
    try:
        handler, _, agent = await prepare_chat_agent(
            session,
            item_id,
            current_user,
            prepared=prepared,
        )
    except Exception:
        lease.release()
        raise

    def serialized_stream() -> Generator[str, None, None]:
        try:
            yield from generate_stream(
                message=request.message,
                history=request.history,
                handler=handler,
                item_id=item_id,
                agent=agent,
                turn_serialized=True,
            )
        finally:
            lease.release()

    return StreamingResponse(
        serialized_stream(),
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
    prepared = _require_chat_handler(session, item_id, current_user)
    lease = await agent_turn_coordinator.acquire_async(
        agent_turn_key(str(prepared[0].id))
    )
    try:
        _, _, agent = await prepare_chat_agent(
            session,
            item_id,
            current_user,
            prepared=prepared,
        )
        matched = agent.match_skills(query)
    finally:
        lease.release()
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


def _cancel_running_daemon_job(session: SessionDep, item_id: str) -> dict[str, Any]:
    try:
        item_uuid = UUID(str(item_id))
    except ValueError:
        return {"success": False, "error": "Invalid item_id"}

    item = session.get(Item, item_uuid)
    if not item:
        return {"success": False, "error": "Item not found"}
    if not item.socket_host or not item.socket_port or not item.api_key:
        return {"success": False, "error": "Daemon is not configured"}

    try:
        from app.services import DaemonConfig, connection_manager

        daemon_config = DaemonConfig(item.socket_host, item.socket_port, item.api_key)
        connection = connection_manager.get_or_create_connection(daemon_config)
        return connection.cancel_job_http(item_uuid=str(item_uuid))
    except Exception as exc:
        logger.warning("Failed to cancel daemon job for item %s: %s", item_id, exc)
        return {"success": False, "error": str(exc)}


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
    cancel_result: dict[str, Any] | None = None
    if active_session:
        has_running_job = active_session.has_running_terminal_job()
        active_session.abort(clear_queue=True)
        if has_running_job:
            cancel_result = _cancel_running_daemon_job(session, item_id)
            if (
                cancel_result.get("success")
                or cancel_result.get("cancelled")
                or cancel_result.get("error") == "No running job for item"
            ):
                active_session.clear_terminal_job()
                active_session.emit_output(
                    "\u540e\u53f0\u4efb\u52a1\u5df2\u4e2d\u65ad\uff0c\u7ec8\u7aef\u9501\u5df2\u91ca\u653e\u3002",
                    "agent_warning",
                )
            else:
                active_session.emit_output(
                    f"\u540e\u53f0\u4efb\u52a1\u4e2d\u65ad\u5931\u8d25: {cancel_result.get('error', 'unknown error')}",
                    "agent_warning",
                )
        active_session.emit_output("\u672c\u6b21\u4f1a\u8bdd\u5df2\u4e2d\u65ad", "agent_warning")
        active_session.emit_status("idle", "")

    return {"success": True, "message": "Chat aborted", "cancel_result": cancel_result}
