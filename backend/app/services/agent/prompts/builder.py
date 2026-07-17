import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.services.agent.history.chat import (
    SESSION_SUMMARY_TYPE,
    get_chat_messages,
)
from app.services.agent.installed_software import build_installed_software_prompt
from app.services.agent.integrations import (
    annotate_integration_history_events,
    build_integration_history_prompt,
    integration_history_event_matches_scopes,
)
from app.services.agent.knowledge.service import knowledge_base_service
from app.services.agent.memory.vector_store import MEMORY_TYPES, vector_store
from app.services.agent.prompts.policy import (
    PromptTurnType,
    resolve_memory_status,
    resolve_prompt_memory_policy,
)
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.skills import skill_loader
from app.services.agent.task_workflow import task_workflow_manager

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
NON_MODEL_CONTEXT_TYPES = {
    "agent_qq_reply",
}

TERMINAL_CRITICAL_ALERT_SKILL_ID = "terminal_mcp"
CURRENT_SOURCE_ROUTE_LABEL = "Current source route"

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
MIN_LONG_TERM_MEMORY_RELEVANCE = 0.32
LONG_TERM_MEMORY_SCORE_MARGIN = 0.18
LONG_TERM_MEMORY_DIVERSITY_PENALTY = 0.22
MAX_LONG_TERM_MEMORIES_PER_TYPE = 2
DEFAULT_RECENT_CONTEXT_MESSAGES = 4
ALWAYS_ON_SKILL_CATEGORIES: set[str] = set()
ALWAYS_ON_MEMORY_TYPES = {"preference", "fact", "context", "error"}
MAX_ALWAYS_ON_MEMORIES_PER_TYPE = 2
MAX_ALWAYS_ON_MEMORIES_TOTAL = 2
ALWAYS_ON_RECENT_DAYS = 14
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
    "error": 0.14,
    "context": 0.08,
    "fact": 0.04,
}
PINNED_MEMORY_TYPES = ("preference", "error")
ALWAYS_ON_MEMORY_SOURCES = {
    "chat_user",
    "local_agent_saved",
    "qq_robot",
    "qq_robot_agent",
    "qq_robot_auto",
    "qq_robot_auto_promoted",
}
ALWAYS_ON_MEMORY_RECORD_TYPES = {
    "agent_saved",
    "conversation_explicit",
    "conversation_auto_candidate",
    "conversation_auto_promoted",
    "robot_agent_saved",
}
CONTEXT_DEPENDENT_QUERY_RE = re.compile(
    r"(?:为什么|怎么回事|什么意思|然后呢|后来呢|继续|接着|刚才|刚刚|上面|前面|之前|"
    r"这个|那个|这件事|那件事|现在呢|怎么样了|完成了吗|好了吗|成功了吗|失败了吗|"
    r"\b(?:why|continue|again|then|that|this|it|he|she|done|ready|status|what about)\b)",
    re.IGNORECASE,
)


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


def _robot_memory_scope_rank(agent: "Agent | None", memory: dict[str, Any]) -> int:
    metadata = memory.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    has_robot_scope = bool(
        str(metadata.get("robot_id") or "").strip()
        or str(metadata.get("robot_conversation_key") or "").strip()
        or str(metadata.get("conversation_key") or "").strip()
        or str(metadata.get("speaker_global_key") or "").strip()
        or str(metadata.get("speaker_key") or "").strip()
        or str(metadata.get("memory_scope") or "").strip()
    )
    context = getattr(agent, "_context", None) if agent is not None else None
    robot_id = str(getattr(context, "robot_id", "") or "").strip()
    conversation_key = str(getattr(context, "robot_conversation_key", "") or "").strip()
    sender_key = str(getattr(context, "robot_sender_key", "") or "").strip()

    if not robot_id and not conversation_key:
        return -1 if has_robot_scope else 1

    try:
        from app.plugins.robot.memory_scope import (
            memory_scope_rank,
            speaker_global_key_from_context,
        )

        return memory_scope_rank(
            memory,
            robot_id=robot_id,
            conversation_key=conversation_key,
            speaker_global_key=speaker_global_key_from_context(sender_key),
        )
    except Exception as exc:
        logger.debug("[PromptBuilder] Failed to rank robot memory scope: %s", exc)
        memory_conversation = str(
            metadata.get("robot_conversation_key")
            or metadata.get("conversation_key")
            or ""
        ).strip()
        if memory_conversation:
            return 4 if memory_conversation == conversation_key else -1
        memory_robot_id = str(metadata.get("robot_id") or "").strip()
        if memory_robot_id:
            return 2 if memory_robot_id == robot_id else -1
        return 1


def _is_recent_memory(memory: dict[str, Any], days: int = ALWAYS_ON_RECENT_DAYS) -> bool:
    metadata = memory.get("metadata") or {}
    timestamp = _parse_memory_datetime(
        metadata.get("updated_at") or metadata.get("created_at")
    )
    if timestamp is None:
        return False
    now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()
    return 0 <= (now - timestamp).days <= days


def _is_sticky_long_term_memory(memory: dict[str, Any]) -> bool:
    metadata = memory.get("metadata") or {}
    memory_type = _memory_type(memory)
    status = str(resolve_memory_status(memory) or "").lower()
    source = str(metadata.get("source") or "").strip()
    record_type = str(metadata.get("type") or "").strip()

    if _looks_like_preference_memory(memory):
        return True
    if memory_type == "error" and status in {"active", ""}:
        return True
    if metadata.get("verified") is True:
        return True
    if source in ALWAYS_ON_MEMORY_SOURCES:
        return True
    if record_type in ALWAYS_ON_MEMORY_RECORD_TYPES:
        return True
    return _is_recent_memory(memory)


def _always_on_memory_sort_key(memory: dict[str, Any]) -> tuple[float, float]:
    metadata = memory.get("metadata") or {}
    sticky_bonus = 0.0
    if metadata.get("verified") is True:
        sticky_bonus += 0.25
    if str(metadata.get("source") or "") in ALWAYS_ON_MEMORY_SOURCES:
        sticky_bonus += 0.18
    if str(metadata.get("type") or "") in ALWAYS_ON_MEMORY_RECORD_TYPES:
        sticky_bonus += 0.16
    if _looks_like_preference_memory(memory):
        sticky_bonus += 0.14
    if _is_recent_memory(memory, days=7):
        sticky_bonus += 0.12
    return (_memory_rank_score(memory) + sticky_bonus, _memory_timestamp(memory))


def _collect_always_on_memories(
    item_id: str,
    *,
    allowed_types: tuple[str, ...],
    agent: "Agent | None" = None,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    if not allowed_types:
        return collected

    memory_types = [
        memory_type
        for memory_type in allowed_types
        if memory_type in ALWAYS_ON_MEMORY_TYPES
    ]
    try:
        all_memories = vector_store.get_all_memories(item_id)
    except Exception as exc:
        logger.warning(
            "[PromptBuilder] Failed to load always-on memories for item=%s: %s",
            item_id,
            exc,
        )
        return collected
    for memory_type in memory_types:
        active_memories = [
            memory
            for memory in all_memories
            if memory.get("content")
            and _memory_type(memory) == memory_type
            and _is_sticky_long_term_memory(memory)
            and not _is_memory_expired(memory)
            and not _is_inactive_status_memory(memory)
            and _robot_memory_scope_rank(agent, memory) >= 0
        ]
        collected.extend(
            sorted(
                active_memories,
                key=_always_on_memory_sort_key,
                reverse=True,
            )[:MAX_ALWAYS_ON_MEMORIES_PER_TYPE]
        )

    return sorted(
        collected,
        key=_always_on_memory_sort_key,
        reverse=True,
    )[:MAX_ALWAYS_ON_MEMORIES_TOTAL]


def _query_memory_scope_usable(agent: "Agent | None", memory: dict[str, Any]) -> bool:
    return _robot_memory_scope_rank(agent, memory) >= 0


def _normalize_content(value: str) -> str:
    return (value or "").strip()


def _event_to_model_message(event: dict[str, Any]) -> dict[str, str] | None:
    message_type = event.get("type")
    content = _normalize_content(str(event.get("content", "")))
    role = event.get("role")

    if not content:
        return None

    if message_type in NON_MODEL_CONTEXT_TYPES:
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


def _message_needs_expanded_history(message: str) -> bool:
    compact = re.sub(r"\s+", "", str(message or "").strip())
    if not compact:
        return False
    if CONTEXT_DEPENDENT_QUERY_RE.search(compact):
        return True
    return len(compact) <= 6 and bool(
        re.search(r"(?:呢|吗|了|它|他|她|这|那)$", compact, flags=re.IGNORECASE)
    )


def _recent_context_limit(message: str, maximum: int) -> int:
    if maximum <= 0:
        return 0
    if _message_needs_expanded_history(message):
        return maximum
    return min(DEFAULT_RECENT_CONTEXT_MESSAGES, maximum)


def _latest_session_summary_from_messages(
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("type") == SESSION_SUMMARY_TYPE:
            return message
    return None


def _build_memory_retrieval_query(
    query: str,
    recent_context_messages: list[dict[str, str]],
) -> str:
    normalized_query = str(query or "").strip()
    if not normalized_query or not _message_needs_expanded_history(normalized_query):
        return normalized_query

    prior_parts: list[str] = []
    for message in reversed(recent_context_messages):
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        if not content or content == normalized_query:
            continue
        prior_parts.append(content[:240])
        if len(prior_parts) >= 2:
            break
    if not prior_parts:
        return normalized_query
    prior_parts.reverse()
    return f"{normalized_query}\nPrevious conversation context:\n" + "\n".join(prior_parts)


def _collect_recent_context_messages(
    agent: "Agent",
    item_id: str,
    *,
    max_messages: int,
    exclude_terminal_content: str = "",
    all_messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    if all_messages is None:
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
    agent: "Agent | None" = None,
) -> str:
    allowed_types = tuple(
        memory_type for memory_type in allowed_types if memory_type in MEMORY_TYPES
    )
    if not allowed_types or n_results <= 0:
        return ""

    collected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for memory in _collect_always_on_memories(
        item_id,
        allowed_types=allowed_types,
        agent=agent,
    ):
        memory_id = memory.get("id")
        if memory_id in seen_ids:
            continue
        seen_ids.add(memory_id)
        collected.append(memory)

    if query:
        try:
            memories = vector_store.search_memories(
                item_id=item_id,
                query=query,
                n_results=max(12, n_results * 4),
                include_expired=False,
                active_only=True,
                min_similarity=0.18,
            )
        except Exception as exc:
            logger.warning(
                "[PromptBuilder] Failed to query long-term memories for item=%s: %s",
                item_id,
                exc,
            )
            memories = []
        for memory in memories:
            if _memory_type(memory) not in allowed_types:
                continue
            if not _query_memory_scope_usable(agent, memory):
                continue
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
        normalized_distance = min(max(float(distance), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.25
    return max(0.0, 1.0 - normalized_distance)


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
    if _memory_type(memory) in {"preference", "error"}:
        return False
    expires_at = _parse_memory_datetime(metadata.get("expires_at"))
    if expires_at is None:
        return False
    now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
    return expires_at < now


def _is_inactive_status_memory(memory: dict[str, Any]) -> bool:
    memory_type = _memory_type(memory)
    status = str(resolve_memory_status(memory) or "").lower()
    return memory_type == "task" and status == "completed"


def _memory_rank_score(memory: dict[str, Any]) -> float:
    metadata = memory.get("metadata") or {}
    verified_bonus = 0.1 if metadata.get("verified") is True else 0.0
    return (
        _memory_relevance_score(memory)
        + MEMORY_TYPE_RANK_BONUS.get(_memory_type(memory), 0.0)
        + verified_bonus
        + _memory_recency_score(memory)
    )


def _memory_content_tokens(memory: dict[str, Any]) -> set[str]:
    content = str(memory.get("content") or "").casefold()
    chinese = re.findall(r"[\u4e00-\u9fff]", content)
    tokens = set(chinese)
    tokens.update(
        "".join(chinese[index : index + 2])
        for index in range(max(len(chinese) - 1, 0))
    )
    tokens.update(re.findall(r"[a-z0-9][a-z0-9_.:/-]*", content))
    return {token for token in tokens if token}


def _memory_content_similarity(
    left: dict[str, Any],
    right: dict[str, Any],
) -> float:
    left_tokens = _memory_content_tokens(left)
    right_tokens = _memory_content_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _select_long_term_memories(
    memories: list[dict[str, Any]],
    *,
    allowed_types: tuple[str, ...],
    n_results: int,
) -> list[dict[str, Any]]:
    query_relevances = [
        _memory_relevance_score(memory)
        for memory in memories
        if memory.get("distance") is not None
    ]
    dynamic_threshold = MIN_LONG_TERM_MEMORY_RELEVANCE
    if query_relevances:
        dynamic_threshold = max(
            MIN_LONG_TERM_MEMORY_RELEVANCE,
            max(query_relevances) - LONG_TERM_MEMORY_SCORE_MARGIN,
        )
    candidates = [
        memory
        for memory in memories
        if memory.get("content")
        and _memory_type(memory) in allowed_types
        and not _is_memory_expired(memory)
        and not _is_inactive_status_memory(memory)
        and (
            (
                memory.get("distance") is None
                and _is_sticky_long_term_memory(memory)
            )
            or _memory_relevance_score(memory) >= dynamic_threshold
        )
    ]
    if not candidates:
        return []

    candidates.sort(key=_memory_rank_score, reverse=True)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    selected_type_counts: dict[str, int] = {}

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
        selected_type_counts[memory_type] = selected_type_counts.get(memory_type, 0) + 1

    remaining = [
        memory
        for memory in candidates
        if str(memory.get("id") or id(memory)) not in selected_ids
    ]
    while remaining and len(selected) < n_results:
        scored: list[tuple[float, float, dict[str, Any]]] = []
        for memory in remaining:
            memory_type = _memory_type(memory)
            if selected_type_counts.get(memory_type, 0) >= MAX_LONG_TERM_MEMORIES_PER_TYPE:
                continue
            max_similarity = max(
                (_memory_content_similarity(memory, chosen) for chosen in selected),
                default=0.0,
            )
            adjusted_score = (
                _memory_rank_score(memory)
                - LONG_TERM_MEMORY_DIVERSITY_PENALTY * max_similarity
            )
            scored.append((adjusted_score, _memory_timestamp(memory), memory))
        if not scored:
            break
        scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        chosen = scored[0][2]
        selected.append(chosen)
        selected_ids.add(str(chosen.get("id") or id(chosen)))
        chosen_type = _memory_type(chosen)
        selected_type_counts[chosen_type] = selected_type_counts.get(chosen_type, 0) + 1
        remaining = [memory for memory in remaining if memory is not chosen]

    selected.sort(key=_memory_rank_score, reverse=True)
    return selected[:n_results]


def _format_long_term_memory(memory: dict[str, Any]) -> str:
    metadata = memory.get("metadata") or {}
    content = str(memory.get("content") or "").strip()
    sender = str(
        metadata.get("speaker")
        or metadata.get("speaker_label")
        or metadata.get("sender")
        or ""
    ).strip()
    prefix = f"{sender}: " if sender and not content.startswith(sender) else ""
    return f"- {prefix}{content}"


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


def _build_pending_reply_context(
    item_id: str,
    current_input: str,
    agent: "Agent | None" = None,
) -> str:
    try:
        from app.services.agent.reply_ticket import reply_ticket_manager

        context = getattr(agent, "_context", None) if agent is not None else None
        current_ticket_id = str(
            getattr(context, "reply_ticket_id", "") or ""
        ).strip()
        return reply_ticket_manager.build_pending_reply_prompt(
            item_id,
            current_input=current_input,
            current_ticket_id=current_ticket_id,
        )
    except Exception as exc:
        logger.warning("[PromptBuilder] Failed to build pending reply context: %s", exc)
        return ""


def _build_current_source_route_context(
    agent: "Agent",
    *,
    source: str,
) -> str:
    context = getattr(agent, "_context", None)
    robot_id = str(getattr(context, "robot_id", "") or "").strip()
    robot_conversation_key = str(
        getattr(context, "robot_conversation_key", "") or ""
    ).strip()
    if robot_id:
        route = robot_conversation_key or "current QQ conversation"
        return (
            f"{CURRENT_SOURCE_ROUTE_LABEL}:\n"
            f"- current source: QQ robot conversation ({route})\n"
            "- reply contract: if visible reply is needed, use mcp_robot_send_message "
            "to the locked current QQ context; do not leave the answer only in the "
            "TermMan web chat.\n"
            "- one-turn reply contract: one QQ input should produce one logical QQ reply via one "
            "send-tool call and one visible `text` bubble. Do not split one answer into a reaction "
            "and follow-up. Use `messages` only for a pending batch where multiple distinct senders "
            "each need one separate answer; consecutive messages from the same sender are one intent. "
            "After `mcp_robot_send_message` succeeds, do not restate the same answer in the final assistant text.\n"
            "- do not send to any other QQ conversation unless the user explicitly "
            "gave a target and the tool allows it."
        )

    if source == "terminal":
        return (
            f"{CURRENT_SOURCE_ROUTE_LABEL}:\n"
            "- current source: terminal/server output, not QQ and not normal web chat.\n"
            "- reply contract: if a server player/user is talking to the agent, reply "
            "back through the same terminal/server using mcp_local_execute_command "
            "with an appropriate say/tell/console command.\n"
            "- do not use QQ tools unless a separate pending-source context explicitly "
            "says this terminal feedback belongs to a QQ-started request."
        )

    return (
        f"{CURRENT_SOURCE_ROUTE_LABEL}:\n"
        "- current source: TermMan web chat.\n"
        "- reply contract: answer in the normal assistant response for this web chat.\n"
        "- do not use QQ tools unless the user explicitly asks to send a message to "
        "a specific QQ target."
    )


def _build_active_task_ledger_context(
    item_id: str,
    agent: "Agent | None" = None,
) -> str:
    context = getattr(agent, "_context", None) if agent is not None else None
    reply_ticket_id = str(getattr(context, "reply_ticket_id", "") or "").strip()
    workflow_context = task_workflow_manager.build_prompt_context(
        item_id=item_id,
        reply_ticket_id=reply_ticket_id,
    )
    return workflow_context or ""

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
    pending_context: str = "",
) -> list[dict[str, str]]:
    effective_query = query or message
    policy = resolve_prompt_memory_policy(PromptTurnType.CHAT)
    history_events: list[dict[str, Any]] = []
    recent_context_messages: list[dict[str, str]] = []
    if not latest_only_context and (
        policy.include_recent_history or policy.include_session_summary
    ):
        history_events = get_chat_messages(item_id)
    if not latest_only_context and policy.include_recent_history:
        recent_context_messages = _collect_recent_context_messages(
            agent,
            item_id,
            max_messages=_recent_context_limit(
                message,
                policy.max_recent_messages,
            ),
            all_messages=history_events,
        )
    retrieval_query = _build_memory_retrieval_query(
        effective_query,
        recent_context_messages,
    )

    extra_prompt_parts: list[str] = []
    source_route_context = _build_current_source_route_context(agent, source="chat")
    if source_route_context:
        extra_prompt_parts.append(source_route_context)
    active_task_ledger_context = _build_active_task_ledger_context(item_id, agent)
    if active_task_ledger_context:
        extra_prompt_parts.append(active_task_ledger_context)
    installed_software_context = _build_installed_software_context(item_id)
    if installed_software_context:
        extra_prompt_parts.append(installed_software_context)
    pending_reply_context = _build_pending_reply_context(item_id, message, agent)
    if pending_reply_context:
        extra_prompt_parts.append(pending_reply_context)
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
        summary = _latest_session_summary_from_messages(history_events)
        if summary and summary.get("content"):
            prompt_messages.append(
                {"role": "system", "content": f"{SESSION_SUMMARY_LABEL}:\n{summary['content']}"}
            )

    if not latest_only_context and policy.include_recent_history:
        prompt_messages.extend(recent_context_messages)

    if policy.include_long_term:
        memories = _collect_long_term_memories(
            item_id,
            retrieval_query,
            allowed_types=policy.allowed_long_term_types,
            n_results=policy.max_long_term_memories,
            agent=agent,
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

    if pending_context.strip():
        prompt_messages.append({"role": "system", "content": pending_context.strip()})

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
    pending_source_context: str = "",
) -> list[dict[str, str]]:
    turn_type = (
        PromptTurnType.TERMINAL_RAW_FEEDBACK
        if terminal_source == "raw_feedback"
        else PromptTurnType.TERMINAL_FILTERED
    )
    policy = resolve_prompt_memory_policy(turn_type)
    effective_query = query or terminal_content
    history_events: list[dict[str, Any]] = []
    recent_context_messages: list[dict[str, str]] = []
    if policy.include_recent_history or policy.include_session_summary:
        history_events = get_chat_messages(item_id)
    if policy.include_recent_history:
        recent_context_messages = _collect_recent_context_messages(
            agent,
            item_id,
            max_messages=_recent_context_limit(
                effective_query,
                policy.max_recent_messages,
            ),
            exclude_terminal_content=terminal_content,
            all_messages=history_events,
        )
    retrieval_query = _build_memory_retrieval_query(
        effective_query,
        recent_context_messages,
    )
    extra_prompt_parts: list[str] = []
    source_route_context = _build_current_source_route_context(agent, source="terminal")
    if source_route_context:
        extra_prompt_parts.append(source_route_context)
    active_task_ledger_context = _build_active_task_ledger_context(item_id, agent)
    if active_task_ledger_context:
        extra_prompt_parts.append(active_task_ledger_context)
    installed_software_context = _build_installed_software_context(item_id)
    if installed_software_context:
        extra_prompt_parts.append(installed_software_context)
    pending_reply_context = _build_pending_reply_context(
        item_id,
        terminal_content,
        agent,
    )
    if pending_reply_context:
        extra_prompt_parts.append(pending_reply_context)
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
            "如果日志里同时出现旧的加载中信息和新的完成信息，只输出最新、最有决定性的状态；"
            "不要把同一个任务拆成多条状态回复。"
        )
        prompt_messages.append({"role": "system", "content": raw_feedback_notice})
        if pending_command:
            prompt_messages.append(
                {"role": "system", "content": f"当前等待确认的命令:\n{pending_command}"}
            )
        if pending_source_context.strip():
            prompt_messages.append(
                {"role": "system", "content": pending_source_context.strip()}
            )
    else:
        terminal_source_notice = (
            "来源路由规则：当前输入来自 TermMan 终端流，不是普通网页聊天。"
            "如果终端内容是服务器内玩家/用户在问你、叫你、回复你，回答必须回到同一个来源。"
            "Minecraft/类 Minecraft 控制台请调用 `mcp_local_execute_command`，用 `say <回复内容>` 广播回复，"
            "或用 `tell <玩家名> <回复内容>` 私聊回复。"
            "不要只在 TermMan 聊天框输出最终回答。"
            "如果只是普通日志、命令状态、服务器提示，或没人和你说话，就不要往服务器发消息。"
        )
        prompt_messages.append({"role": "system", "content": terminal_source_notice})

    if policy.include_session_summary:
        summary = _latest_session_summary_from_messages(history_events)
        if summary and summary.get("content"):
            prompt_messages.append(
                {"role": "system", "content": f"{SESSION_SUMMARY_LABEL}:\n{summary['content']}"}
            )

    if policy.include_recent_history:
        prompt_messages.extend(recent_context_messages)

    if policy.include_long_term:
        memories = _collect_long_term_memories(
            item_id,
            retrieval_query,
            allowed_types=policy.allowed_long_term_types,
            n_results=policy.max_long_term_memories,
            agent=agent,
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
