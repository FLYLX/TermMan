from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.agent.chat_history import (
    SESSION_SUMMARY_TYPE,
    get_chat_messages,
    get_latest_session_summary,
)
from app.services.agent.memory.vector_store import vector_store
from app.services.agent.memory_policy import PromptTurnType, resolve_prompt_memory_policy
from app.services.agent.prompting import get_system_prompt

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


logger = logging.getLogger(__name__)


ASSISTANT_CONTEXT_TYPES = {
    "agent_action",
    "agent_tool_result",
    "agent_response",
    "agent_warning",
    "agent_error",
}


def _build_skill_prompt(agent: "Agent", query: str) -> str:
    prompt_parts = [get_system_prompt(agent)]

    skills = agent.match_skills(query) if query else []
    for skill in skills:
        if skill.category == "system":
            continue
        if skill.action and skill.action.prompt:
            prompt_parts.append(skill.action.prompt)

    base_prompt = "\n\n".join(part.strip() for part in prompt_parts if part and part.strip())
    if query:
        return f"{base_prompt}\n\nUser query: {query}"
    return base_prompt


def _normalize_content(value: str) -> str:
    return (value or "").strip()


def _event_to_model_message(event: dict[str, Any]) -> dict[str, str] | None:
    message_type = event.get("type")
    content = _normalize_content(str(event.get("content", "")))
    role = event.get("role")

    if not content:
        return None

    if message_type == SESSION_SUMMARY_TYPE:
        return {"role": "system", "content": f"共享会话摘要:\n{content}"}

    if message_type == "chat_user" or role == "user":
        return {"role": "user", "content": content}

    if message_type == "terminal_output" or role == "terminal":
        return {"role": "user", "content": f"终端过滤输出:\n{content}"}

    if message_type in ASSISTANT_CONTEXT_TYPES or role == "assistant":
        return {"role": "assistant", "content": content}

    return None


def _collect_recent_context_messages(
    item_id: str,
    *,
    max_messages: int,
    exclude_terminal_content: str = "",
) -> list[dict[str, str]]:
    all_messages = get_chat_messages(item_id)
    if not all_messages or max_messages <= 0:
        return []

    normalized_excluded_terminal = _normalize_content(exclude_terminal_content)
    remaining_terminal_exclusion = bool(normalized_excluded_terminal)

    filtered_events: list[dict[str, Any]] = []
    for event in reversed(all_messages):
        if event.get("type") == SESSION_SUMMARY_TYPE:
            continue
        if (
            remaining_terminal_exclusion
            and event.get("type") == "terminal_output"
            and _normalize_content(str(event.get("content", ""))) == normalized_excluded_terminal
        ):
            remaining_terminal_exclusion = False
            continue
        filtered_events.append(event)
        if len(filtered_events) >= max_messages:
            break

    context_messages: list[dict[str, str]] = []
    for event in reversed(filtered_events):
        model_message = _event_to_model_message(event)
        if model_message:
            context_messages.append(model_message)
    return context_messages


def _collect_long_term_memories(
    item_id: str,
    query: str,
    *,
    allowed_types: tuple[str, ...],
    n_results: int,
) -> str:
    if not query or not allowed_types or n_results <= 0:
        return ""

    collected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for memory_type in allowed_types:
        try:
            memories = vector_store.search_memories(
                item_id=item_id,
                query=query,
                n_results=n_results,
                memory_type=memory_type,
            )
        except Exception as exc:
            logger.warning(
                "[PromptBuilder] Failed to query long-term memories for item=%s, type=%s: %s",
                item_id,
                memory_type,
                exc,
            )
            return ""
        for memory in memories:
            memory_id = memory.get("id")
            if memory_id in seen_ids:
                continue
            seen_ids.add(memory_id)
            collected.append(memory)

    collected.sort(key=lambda memory: memory.get("distance") or 0)
    trimmed = collected[:n_results]
    if not trimmed:
        return ""

    return "\n".join(f"- {memory['content']}" for memory in trimmed if memory.get("content"))


def _dedupe_adjacent_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    for message in messages:
        if deduped and deduped[-1] == message:
            continue
        deduped.append(message)
    return deduped


def build_chat_turn_messages(
    agent: "Agent",
    *,
    item_id: str,
    message: str,
    query: str = "",
) -> list[dict[str, str]]:
    effective_query = query or message
    policy = resolve_prompt_memory_policy(PromptTurnType.CHAT)
    prompt_messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_skill_prompt(agent, effective_query)}
    ]

    if policy.include_session_summary:
        summary = get_latest_session_summary(item_id)
        if summary and summary.get("content"):
            prompt_messages.append(
                {"role": "system", "content": f"共享会话摘要:\n{summary['content']}"}
            )

    if policy.include_recent_history:
        prompt_messages.extend(
            _collect_recent_context_messages(
                item_id,
                max_messages=policy.max_recent_messages,
            )
        )

    if policy.include_long_term:
        memories = _collect_long_term_memories(
            item_id,
            effective_query,
            allowed_types=policy.allowed_long_term_types,
            n_results=policy.max_long_term_memories,
        )
        if memories:
            prompt_messages.append({"role": "system", "content": f"相关长期记忆:\n{memories}"})

    prompt_messages.append({"role": "user", "content": message.strip()})
    return _dedupe_adjacent_messages(prompt_messages)


def build_terminal_turn_messages(
    agent: "Agent",
    *,
    item_id: str,
    terminal_content: str,
    query: str = "",
    terminal_source: str = "filtered_output",
    pending_command: str = "",
) -> list[dict[str, str]]:
    turn_type = (
        PromptTurnType.TERMINAL_RAW_FEEDBACK
        if terminal_source == "raw_feedback"
        else PromptTurnType.TERMINAL_FILTERED
    )
    policy = resolve_prompt_memory_policy(turn_type)
    effective_query = query or terminal_content
    prompt_messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_skill_prompt(agent, effective_query)}
    ]

    if turn_type == PromptTurnType.TERMINAL_RAW_FEEDBACK:
        raw_feedback_notice = (
            "当前输入是已发送命令的原生日志反馈。"
            "只根据当前日志判断结果，不要依赖长期记忆猜测，不要重复发送同一命令。"
            "没有新的日志证据时，不要擅自断言命令已经成功。"
        )
        prompt_messages.append({"role": "system", "content": raw_feedback_notice})
        if pending_command:
            prompt_messages.append(
                {"role": "system", "content": f"当前等待确认的命令:\n{pending_command}"}
            )

    if policy.include_session_summary:
        summary = get_latest_session_summary(item_id)
        if summary and summary.get("content"):
            prompt_messages.append(
                {"role": "system", "content": f"共享会话摘要:\n{summary['content']}"}
            )

    if policy.include_recent_history:
        prompt_messages.extend(
            _collect_recent_context_messages(
                item_id,
                max_messages=policy.max_recent_messages,
                exclude_terminal_content=terminal_content,
            )
        )

    if policy.include_long_term:
        memories = _collect_long_term_memories(
            item_id,
            effective_query,
            allowed_types=policy.allowed_long_term_types,
            n_results=policy.max_long_term_memories,
        )
        if memories:
            prompt_messages.append({"role": "system", "content": f"相关长期记忆:\n{memories}"})

    source_label = "终端过滤输出"
    if turn_type == PromptTurnType.TERMINAL_RAW_FEEDBACK:
        source_label = "命令原生日志反馈"

    prompt_messages.append(
        {
            "role": "user",
            "content": f"{source_label}:\n{terminal_content.strip()}",
        }
    )
    return _dedupe_adjacent_messages(prompt_messages)
