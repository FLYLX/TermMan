import logging
from typing import TYPE_CHECKING, Any

from app.services.agent.history.chat import (
    SESSION_SUMMARY_TYPE,
    get_chat_messages,
    get_latest_session_summary,
)
from app.services.agent.knowledge.service import knowledge_base_service
from app.services.agent.memory.vector_store import vector_store
from app.services.agent.prompts.policy import (
    PromptTurnType,
    resolve_prompt_memory_policy,
)
from app.services.agent.prompts.system import get_system_prompt

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

SESSION_SUMMARY_LABEL = "会话摘要"
LONG_TERM_MEMORY_LABEL = "相关长期记忆"
FILTERED_TERMINAL_LABEL = "终端过滤输出"
RAW_TERMINAL_LABEL = "原生日志反馈"


def _build_skill_prompt(
    agent: "Agent",
    query: str,
    *,
    force_skill_ids: set[str] | None = None,
) -> str:
    prompt_parts = [get_system_prompt(agent)]

    skills = agent.match_skills(query) if query else []
    if force_skill_ids:
        existing_skill_ids = {skill.skill_id for skill in skills}
        for skill in agent.get_skills():
            if skill.skill_id in force_skill_ids and skill.skill_id not in existing_skill_ids:
                skills.append(skill)
                existing_skill_ids.add(skill.skill_id)
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
        return {"role": "system", "content": f"{SESSION_SUMMARY_LABEL}:\n{content}"}

    if message_type == "chat_user" or role == "user":
        return {"role": "user", "content": content}

    if message_type == "terminal_output" or role == "terminal":
        return {"role": "user", "content": f"{FILTERED_TERMINAL_LABEL}:\n{content}"}

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


def _collect_handler_knowledge(
    agent: "Agent",
    query: str,
    *,
    n_results: int,
) -> str:
    enabled_files = getattr(agent, "enabled_knowledge_files", [])
    if not enabled_files or not query or n_results <= 0:
        return ""

    results = knowledge_base_service.search(
        query,
        enabled_files=enabled_files,
        n_results=n_results,
    )
    if not results:
        return ""

    lines: list[str] = []
    for entry in results:
        content = (entry.get("content") or "").strip()
        if not content:
            continue
        metadata = entry.get("metadata") or {}
        file_name = metadata.get("file_name") or metadata.get("file_path") or "knowledge"
        lines.append(f"- [{file_name}] {content}")

    return "\n".join(lines)


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
    recent_context_messages: list[dict[str, str]] = []
    if policy.include_recent_history:
        recent_context_messages = _collect_recent_context_messages(
            item_id,
            max_messages=policy.max_recent_messages,
        )

    force_skill_ids: set[str] = set()
    has_robot_context = "[Robot message;" in message or any(
        "[Robot message;" in context_message.get("content", "")
        for context_message in recent_context_messages
    )
    if has_robot_context:
        force_skill_ids.add("robot_messaging")

    prompt_messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": _build_skill_prompt(
                agent,
                effective_query,
                force_skill_ids=force_skill_ids,
            ),
        }
    ]

    if policy.include_session_summary:
        summary = get_latest_session_summary(item_id)
        if summary and summary.get("content"):
            prompt_messages.append(
                {"role": "system", "content": f"{SESSION_SUMMARY_LABEL}:\n{summary['content']}"}
            )

    if policy.include_recent_history:
        prompt_messages.extend(recent_context_messages)

    if policy.include_long_term:
        memories = _collect_long_term_memories(
            item_id,
            effective_query,
            allowed_types=policy.allowed_long_term_types,
            n_results=policy.max_long_term_memories,
        )
        if memories:
            prompt_messages.append(
                {"role": "system", "content": f"{LONG_TERM_MEMORY_LABEL}:\n{memories}"}
            )

    knowledge = _collect_handler_knowledge(
        agent,
        effective_query,
        n_results=4,
    )
    if knowledge:
        prompt_messages.append({"role": "system", "content": f"Relevant knowledge files:\n{knowledge}"})

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
            "下面输入的是命令发出后的原生日志反馈。"
            "请只根据当前日志判断状态，不要依赖长期记忆猜测，不要脑补命令已经成功或失败。"
            "如果证据不足，只能说明“命令已发送，等待终端结果确认”或“暂无新反馈”。"
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
                {"role": "system", "content": f"{SESSION_SUMMARY_LABEL}:\n{summary['content']}"}
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
            prompt_messages.append(
                {"role": "system", "content": f"{LONG_TERM_MEMORY_LABEL}:\n{memories}"}
            )

    if turn_type != PromptTurnType.TERMINAL_RAW_FEEDBACK:
        knowledge = _collect_handler_knowledge(
            agent,
            effective_query,
            n_results=4,
        )
        if knowledge:
            prompt_messages.append(
                {"role": "system", "content": f"Relevant knowledge files:\n{knowledge}"}
            )

    source_label = FILTERED_TERMINAL_LABEL
    if turn_type == PromptTurnType.TERMINAL_RAW_FEEDBACK:
        source_label = RAW_TERMINAL_LABEL

    prompt_messages.append(
        {
            "role": "user",
            "content": f"{source_label}:\n{terminal_content.strip()}",
        }
    )
    return _dedupe_adjacent_messages(prompt_messages)
