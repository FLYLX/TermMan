import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.services.agent.history.chat import (
    SESSION_SUMMARY_TYPE,
    get_chat_messages,
    get_latest_session_summary,
)
from app.services.agent.installed_software import build_installed_software_prompt
from app.services.agent.integrations import (
    annotate_integration_history_events,
    build_integration_history_prompt,
    integration_history_event_matches_scopes,
)
from app.services.agent.knowledge.service import knowledge_base_service
from app.services.agent.memory.vector_store import vector_store
from app.services.agent.prompts.policy import (
    PromptTurnType,
    resolve_memory_status,
    resolve_prompt_memory_policy,
)
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.skills import skill_loader

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

TERMINAL_CRITICAL_ALERT_SKILL_ID = "terminal_mcp"

CRITICAL_TERMINAL_PATTERNS = (
    r"\bfatal\b",
    r"\bcritical\b",
    r"\bpanic\b",
    r"\btraceback\s*\(most recent call last\)",
    r"\bunhandled exception\b",
    r"\buncaught exception\b",
    r"\bsegmentation fault\b",
    r"\bsegfault\b",
    r"\bout of memory\b",
    r"\boom(?:\s+killed|\s+kill)?\b",
    r"\bkilled process\b",
    r"\bno space left on device\b",
    r"\bdisk full\b",
    r"\bpermission denied\b.*\b(start|startup|listen|bind|open)\b",
    r"\b(startup|start|boot)\s+(failed|failure)\b",
    r"\b(service|server|process|worker)\s+(crashed|failed|exited|terminated)\b",
    r"\bexited\s+with\s+(?:code|status)\s+[1-9]\d*\b",
    r"\baddress already in use\b",
    r"\beaddrinuse\b",
    r"\u5d29\u6e83",
    r"\u5b95\u673a",
    r"\u81f4\u547d",
    r"\u4e25\u91cd",
    r"\u7d27\u6025",
    r"\u542f\u52a8\u5931\u8d25",
    r"\u670d\u52a1\u505c\u6b62",
)


def is_critical_terminal_event(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(
        re.search(pattern, normalized, flags=re.IGNORECASE)
        for pattern in CRITICAL_TERMINAL_PATTERNS
    )

SESSION_SUMMARY_LABEL = "会话摘要"
LONG_TERM_MEMORY_LABEL = "相关长期记忆"
FILTERED_TERMINAL_LABEL = "终端过滤输出"
RAW_TERMINAL_LABEL = "原生日志反馈"
MIN_LONG_TERM_MEMORY_RELEVANCE = 0.08
ALWAYS_ON_SKILL_CATEGORIES: set[str] = set()
ALWAYS_ON_MEMORY_TYPES = {"preference"}
MAX_ALWAYS_ON_MEMORIES_PER_TYPE = 5
PREFERENCE_LIKE_MEMORY_TYPES = ("preference", "fact", "context")
PREFERENCE_LIKE_MEMORY_MARKERS = (
    "用户偏好",
    "人格",
    "人设",
    "性格",
    "语气",
    "口吻",
    "说话方式",
    "persona",
    "tone",
    "style",
)
MEMORY_TYPE_RANK_BONUS = {
    "preference": 0.18,
    "task": 0.16,
    "error": 0.14,
    "context": 0.08,
    "fact": 0.04,
}
PINNED_MEMORY_TYPES = ("preference", "task", "error")


def _build_skill_prompt(
    agent: "Agent",
    query: str,
    *,
    force_skill_ids: set[str] | None = None,
    extra_prompt_parts: list[str] | None = None,
) -> str:
    prompt_parts = [get_system_prompt(agent)]

    skills = agent.match_skills(query) if query else []
    existing_skill_ids = {skill.skill_id for skill in skills}
    for skill in agent.get_skills():
        if skill.category in ALWAYS_ON_SKILL_CATEGORIES and skill.skill_id not in existing_skill_ids:
            skills.append(skill)
            existing_skill_ids.add(skill.skill_id)
    if force_skill_ids:
        for skill in agent.get_skills():
            if skill.skill_id in force_skill_ids and skill.skill_id not in existing_skill_ids:
                skills.append(skill)
                existing_skill_ids.add(skill.skill_id)
        for skill_id in force_skill_ids - existing_skill_ids:
            forced_skill = skill_loader.get(skill_id)
            if forced_skill is not None:
                skills.append(forced_skill)
                existing_skill_ids.add(forced_skill.skill_id)
    for skill in skills:
        if skill.category in {"system", "persona"}:
            continue
        if skill.action and skill.action.prompt:
            prompt_parts.append(skill.action.prompt)

    if extra_prompt_parts:
        prompt_parts.extend(extra_prompt_parts)

    base_prompt = "\n\n".join(part.strip() for part in prompt_parts if part and part.strip())
    if query:
        return f"{base_prompt}\n\nUser query: {query}"
    return base_prompt


def _memory_timestamp(memory: dict[str, Any]) -> float:
    metadata = memory.get("metadata") or {}
    timestamp = _parse_memory_datetime(
        metadata.get("updated_at") or metadata.get("created_at")
    )
    if timestamp is None:
        return 0.0
    try:
        return timestamp.timestamp()
    except OSError:
        return 0.0


def _sort_memories_by_stability(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        memories,
        key=lambda memory: (
            bool((memory.get("metadata") or {}).get("verified")),
            _memory_timestamp(memory),
        ),
        reverse=True,
    )


def _looks_like_preference_memory(memory: dict[str, Any]) -> bool:
    if _memory_type(memory) == "preference":
        return True
    content = str(memory.get("content") or "").lower()
    return any(marker.lower() in content for marker in PREFERENCE_LIKE_MEMORY_MARKERS)


def _collect_always_on_memories(
    item_id: str,
    *,
    allowed_types: tuple[str, ...],
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    if not allowed_types:
        return collected

    if "preference" not in allowed_types:
        return collected

    for memory_type in PREFERENCE_LIKE_MEMORY_TYPES:
        try:
            memories = vector_store.get_all_memories(item_id, memory_type=memory_type)
        except Exception as exc:
            logger.warning(
                "[PromptBuilder] Failed to load always-on memories for item=%s, type=%s: %s",
                item_id,
                memory_type,
                exc,
            )
            continue

        active_memories = [
            memory
            for memory in memories
            if memory.get("content")
            and _looks_like_preference_memory(memory)
            and not _is_memory_expired(memory)
            and not _is_inactive_status_memory(memory)
        ]
        collected.extend(
            _sort_memories_by_stability(active_memories)[:MAX_ALWAYS_ON_MEMORIES_PER_TYPE]
        )

    return collected


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
    agent: "Agent",
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
    all_messages, integration_scopes = annotate_integration_history_events(
        agent,
        all_messages,
    )

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
        if not integration_history_event_matches_scopes(event, integration_scopes):
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
    if not allowed_types or n_results <= 0:
        return ""

    collected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for memory in _collect_always_on_memories(item_id, allowed_types=allowed_types):
        memory_id = memory.get("id")
        if memory_id in seen_ids:
            continue
        seen_ids.add(memory_id)
        collected.append(memory)

    if query:
        for memory_type in allowed_types:
            try:
                memories = vector_store.search_memories(
                    item_id=item_id,
                    query=query,
                    n_results=n_results,
                    memory_type=memory_type,
                    include_expired=False,
                    active_only=True,
                )
            except Exception as exc:
                logger.warning(
                    "[PromptBuilder] Failed to query long-term memories for item=%s, type=%s: %s",
                    item_id,
                    memory_type,
                    exc,
                )
                continue
            for memory in memories:
                memory_id = memory.get("id")
                if memory_id in seen_ids:
                    continue
                seen_ids.add(memory_id)
                collected.append(memory)

    trimmed = _select_long_term_memories(
        collected,
        allowed_types=allowed_types,
        n_results=n_results,
    )
    if not trimmed:
        return ""

    return "\n".join(_format_long_term_memory(memory) for memory in trimmed)


def _parse_memory_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _memory_type(memory: dict[str, Any]) -> str:
    metadata = memory.get("metadata") or {}
    memory_type = str(metadata.get("memory_type") or "fact")
    if memory_type in {"fact", "context"}:
        content = str(memory.get("content") or "").lower()
        if any(marker.lower() in content for marker in PREFERENCE_LIKE_MEMORY_MARKERS):
            return "preference"
    return memory_type


def _memory_relevance_score(memory: dict[str, Any]) -> float:
    distance = memory.get("distance")
    if distance is None:
        return 0.25
    try:
        normalized_distance = min(max(float(distance), 0.0), 2.0)
    except (TypeError, ValueError):
        return 0.25
    return max(0.0, 1.0 - normalized_distance / 2.0)


def _memory_recency_score(memory: dict[str, Any]) -> float:
    metadata = memory.get("metadata") or {}
    timestamp = _parse_memory_datetime(
        metadata.get("updated_at") or metadata.get("created_at")
    )
    if timestamp is None:
        return 0.0

    now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()
    age_days = max(0, (now - timestamp).days)
    if age_days <= 7:
        return 0.08
    if age_days <= 30:
        return 0.05
    if age_days <= 90:
        return 0.02
    return 0.0


def _is_memory_expired(memory: dict[str, Any]) -> bool:
    metadata = memory.get("metadata") or {}
    expires_at = _parse_memory_datetime(metadata.get("expires_at"))
    if expires_at is None:
        return False
    now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
    return expires_at < now


def _is_inactive_status_memory(memory: dict[str, Any]) -> bool:
    memory_type = _memory_type(memory)
    status = str(resolve_memory_status(memory) or "").lower()
    return (
        (memory_type == "task" and status == "completed")
        or (memory_type == "error" and status == "resolved")
    )


def _memory_rank_score(memory: dict[str, Any]) -> float:
    metadata = memory.get("metadata") or {}
    verified_bonus = 0.1 if metadata.get("verified") is True else 0.0
    return (
        _memory_relevance_score(memory)
        + MEMORY_TYPE_RANK_BONUS.get(_memory_type(memory), 0.0)
        + verified_bonus
        + _memory_recency_score(memory)
    )


def _select_long_term_memories(
    memories: list[dict[str, Any]],
    *,
    allowed_types: tuple[str, ...],
    n_results: int,
) -> list[dict[str, Any]]:
    candidates = [
        memory
        for memory in memories
        if memory.get("content")
        and _memory_type(memory) in allowed_types
        and not _is_memory_expired(memory)
        and not _is_inactive_status_memory(memory)
        and _memory_relevance_score(memory) >= MIN_LONG_TERM_MEMORY_RELEVANCE
    ]
    if not candidates:
        return []

    candidates.sort(key=_memory_rank_score, reverse=True)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for memory_type in PINNED_MEMORY_TYPES:
        if memory_type not in allowed_types or len(selected) >= n_results:
            continue
        typed_memory = next(
            (memory for memory in candidates if _memory_type(memory) == memory_type),
            None,
        )
        if typed_memory is None:
            continue
        selected.append(typed_memory)
        selected_ids.add(str(typed_memory.get("id") or id(typed_memory)))

    for memory in candidates:
        if len(selected) >= n_results:
            break
        memory_id = str(memory.get("id") or id(memory))
        if memory_id in selected_ids:
            continue
        selected.append(memory)
        selected_ids.add(memory_id)

    selected.sort(key=_memory_rank_score, reverse=True)
    return selected[:n_results]


def _format_long_term_memory(memory: dict[str, Any]) -> str:
    metadata = memory.get("metadata") or {}
    tags = [_memory_type(memory)]
    status = resolve_memory_status(memory)
    if status:
        tags.append(str(status))
    if metadata.get("verified") is True:
        tags.append("verified")

    content = str(memory.get("content") or "").strip()
    return f"- [{', '.join(tags)}] {content}"


def _collect_handler_knowledge(
    agent: "Agent",
    query: str,
    *,
    n_results: int,
) -> str:
    enabled_files = getattr(agent, "enabled_knowledge_files", [])
    if not enabled_files or not query or n_results <= 0:
        return ""

    try:
        results = knowledge_base_service.search(
            query,
            enabled_files=enabled_files,
            n_results=n_results,
        )
    except Exception as exc:
        logger.warning("[PromptBuilder] Failed to query handler knowledge: %s", exc)
        return ""

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


def _build_installed_software_context(item_id: str) -> str:
    try:
        return build_installed_software_prompt(item_id)
    except Exception as exc:
        logger.warning(
            "[PromptBuilder] Failed to load installed software list for item=%s: %s",
            item_id,
            exc,
        )
        return ""

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
    latest_only_context: bool = False,
) -> list[dict[str, str]]:
    effective_query = query or message
    policy = resolve_prompt_memory_policy(PromptTurnType.CHAT)
    recent_context_messages: list[dict[str, str]] = []
    if not latest_only_context and policy.include_recent_history:
        recent_context_messages = _collect_recent_context_messages(
            agent,
            item_id,
            max_messages=policy.max_recent_messages,
        )

    extra_prompt_parts: list[str] = []
    installed_software_context = _build_installed_software_context(item_id)
    if installed_software_context:
        extra_prompt_parts.append(installed_software_context)
    if not latest_only_context:
        integration_prompt = build_integration_history_prompt(
            agent,
            message=message,
            context_messages=recent_context_messages,
        )
        if integration_prompt:
            extra_prompt_parts.append(integration_prompt)

    prompt_messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": _build_skill_prompt(
                agent,
                effective_query,
                extra_prompt_parts=extra_prompt_parts,
            ),
        }
    ]

    if not latest_only_context and policy.include_session_summary:
        summary = get_latest_session_summary(item_id)
        if summary and summary.get("content"):
            prompt_messages.append(
                {"role": "system", "content": f"{SESSION_SUMMARY_LABEL}:\n{summary['content']}"}
            )

    if not latest_only_context and policy.include_recent_history:
        prompt_messages.extend(recent_context_messages)

    if not latest_only_context and policy.include_long_term:
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

    if not latest_only_context:
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
    extra_prompt_parts: list[str] = []
    installed_software_context = _build_installed_software_context(item_id)
    if installed_software_context:
        extra_prompt_parts.append(installed_software_context)
    prompt_messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": _build_skill_prompt(
                agent,
                effective_query,
                force_skill_ids={TERMINAL_CRITICAL_ALERT_SKILL_ID}
                if is_critical_terminal_event(terminal_content)
                else None,
                extra_prompt_parts=extra_prompt_parts,
            ),
        }
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
                agent,
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
