from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.core.db import engine
from app.models import ItemChatSession

DEFAULT_ROLE_BY_TYPE = {
    "terminal_output": "terminal",
    "chat_user": "user",
    "scheduled_task": "user",
}
SESSION_SUMMARY_TYPE = "session_summary"
SUMMARY_SOURCE_TYPES = {
    "chat_user",
    "chat_assistant",
    "terminal_output",
    "agent_response",
    "agent_warning",
    "agent_error",
}
SUMMARY_MIN_MESSAGE_COUNT = 10
SUMMARY_MIN_CHAR_COUNT = 1200
SUMMARY_REFRESH_MESSAGE_DELTA = 6
SUMMARY_REFRESH_CHAR_DELTA = 600
SUMMARY_MAX_SECTION_ITEMS = 3
SUMMARY_MAX_ITEM_LENGTH = 180


def _get_or_create_chat_session(session: Session, item_id: str) -> ItemChatSession:
    chat_session = session.exec(
        select(ItemChatSession).where(ItemChatSession.item_id == item_id)
    ).first()

    if chat_session:
        return chat_session

    chat_session = ItemChatSession(item_id=item_id, messages=[])
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    return chat_session


def _normalize_message(
    *,
    role: str | None,
    content: str,
    message_type: str | None = None,
    timestamp: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "role": role or DEFAULT_ROLE_BY_TYPE.get(message_type or "", "assistant"),
        "content": content,
        "timestamp": timestamp or datetime.now().isoformat(),
    }

    if message_type:
        normalized["type"] = message_type

    if extra:
        normalized.update(extra)

    return normalized


def _normalize_summary_text(content: str) -> str:
    return " ".join((content or "").strip().split())


def _truncate_summary_text(content: str, limit: int = SUMMARY_MAX_ITEM_LENGTH) -> str:
    normalized = _normalize_summary_text(content)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _get_summary_index(messages: list[dict[str, Any]]) -> int | None:
    for index, message in enumerate(messages):
        if message.get("type") == SESSION_SUMMARY_TYPE:
            return index
    return None


def _get_summary_source_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        message
        for message in messages
        if message.get("type") in SUMMARY_SOURCE_TYPES and str(message.get("content", "")).strip()
    ]


def _get_total_source_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(message.get("content", "")).strip()) for message in messages)


def _collect_summary_section(
    messages: list[dict[str, Any]],
    *,
    allowed_types: set[str],
    item_limit: int = SUMMARY_MAX_SECTION_ITEMS,
) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    for message in reversed(messages):
        if message.get("type") not in allowed_types:
            continue
        content = _truncate_summary_text(str(message.get("content", "")))
        if not content or content in seen:
            continue
        seen.add(content)
        items.append(content)
        if len(items) >= item_limit:
            break

    items.reverse()
    return items


def _build_session_summary_content(messages: list[dict[str, Any]]) -> str:
    goal_items = _collect_summary_section(messages, allowed_types={"chat_user"})
    terminal_items = _collect_summary_section(messages, allowed_types={"terminal_output"})
    result_items = _collect_summary_section(
        messages,
        allowed_types={"agent_response", "agent_warning", "agent_error", "chat_assistant"},
    )

    sections: list[str] = ["当前共享会话摘要"]
    if goal_items:
        sections.append("用户目标:")
        sections.extend(f"- {item}" for item in goal_items)
    if terminal_items:
        sections.append("最近终端:")
        sections.extend(f"- {item}" for item in terminal_items)
    if result_items:
        sections.append("最近结论:")
        sections.extend(f"- {item}" for item in result_items)

    if len(sections) == 1:
        return ""

    return "\n".join(sections)


def _build_session_summary_message(
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    source_messages = _get_summary_source_messages(messages)
    source_count = len(source_messages)
    source_chars = _get_total_source_chars(source_messages)

    if source_count < SUMMARY_MIN_MESSAGE_COUNT and source_chars < SUMMARY_MIN_CHAR_COUNT:
        return None

    content = _build_session_summary_content(source_messages)
    if not content:
        return None

    return _normalize_message(
        role="assistant",
        content=content,
        message_type=SESSION_SUMMARY_TYPE,
        extra={
            "summary_message_count": source_count,
            "summary_char_count": source_chars,
        },
    )


def _should_refresh_session_summary(
    existing_summary: dict[str, Any] | None,
    messages: list[dict[str, Any]],
) -> bool:
    if existing_summary is None:
        return True

    source_messages = _get_summary_source_messages(messages)
    source_count = len(source_messages)
    source_chars = _get_total_source_chars(source_messages)
    previous_count = int(existing_summary.get("summary_message_count") or 0)
    previous_chars = int(existing_summary.get("summary_char_count") or 0)

    return (
        source_count - previous_count >= SUMMARY_REFRESH_MESSAGE_DELTA
        or source_chars - previous_chars >= SUMMARY_REFRESH_CHAR_DELTA
    )


def _apply_session_summary(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary_index = _get_summary_index(messages)
    existing_summary = messages[summary_index] if summary_index is not None else None
    messages_without_summary = [
        message for message in messages if message.get("type") != SESSION_SUMMARY_TYPE
    ]

    next_summary = _build_session_summary_message(messages_without_summary)
    if next_summary is None:
        return messages_without_summary

    if existing_summary and not _should_refresh_session_summary(
        existing_summary,
        messages_without_summary,
    ):
        return [existing_summary, *messages_without_summary]

    return [next_summary, *messages_without_summary]


def append_chat_message(
    item_id: str,
    *,
    role: str | None,
    content: str,
    message_type: str | None = None,
    timestamp: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if content is None:
        raise ValueError("content must not be None")

    message = _normalize_message(
        role=role,
        content=content,
        message_type=message_type,
        timestamp=timestamp,
        extra=extra,
    )

    with Session(engine) as session:
        chat_session = _get_or_create_chat_session(session, item_id)
        existing_messages = list(chat_session.messages or [])
        chat_session.messages = _apply_session_summary([*existing_messages, message])
        session.add(chat_session)
        session.commit()

    return message


def append_chat_messages(item_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return []

    normalized_messages = [
        _normalize_message(
            role=message.get("role"),
            content=str(message.get("content", "")),
            message_type=message.get("type"),
            timestamp=message.get("timestamp"),
            extra={key: value for key, value in message.items() if key not in {"role", "content", "type", "timestamp"}},
        )
        for message in messages
    ]

    with Session(engine) as session:
        chat_session = _get_or_create_chat_session(session, item_id)
        existing_messages = list(chat_session.messages or [])
        chat_session.messages = _apply_session_summary(
            [*existing_messages, *normalized_messages]
        )
        session.add(chat_session)
        session.commit()

    return normalized_messages


def replace_chat_messages(item_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_messages = [
        _normalize_message(
            role=message.get("role"),
            content=str(message.get("content", "")),
            message_type=message.get("type"),
            timestamp=message.get("timestamp"),
            extra={key: value for key, value in message.items() if key not in {"role", "content", "type", "timestamp"}},
        )
        for message in messages
    ]

    with Session(engine) as session:
        chat_session = _get_or_create_chat_session(session, item_id)
        chat_session.messages = _apply_session_summary(normalized_messages)
        session.add(chat_session)
        session.commit()

    return normalized_messages


def get_chat_messages(item_id: str) -> list[dict[str, Any]]:
    with Session(engine) as session:
        chat_session = session.exec(
            select(ItemChatSession).where(ItemChatSession.item_id == item_id)
        ).first()
        if not chat_session or not chat_session.messages:
            return []
        return list(chat_session.messages)


def get_recent_chat_messages(item_id: str, limit: int = 12) -> list[dict[str, Any]]:
    messages = get_chat_messages(item_id)
    if limit <= 0:
        return []
    return messages[-limit:]


def get_latest_session_summary(item_id: str) -> dict[str, Any] | None:
    messages = get_chat_messages(item_id)
    for message in reversed(messages):
        if message.get("type") == SESSION_SUMMARY_TYPE:
            return message
    return None


def get_previous_assistant_response_before_latest_user_message(
    item_id: str,
    user_message: str,
) -> str:
    normalized_user_message = str(user_message or "").strip()
    if not normalized_user_message:
        return ""

    messages = get_chat_messages(item_id)
    found_latest_user = False

    for message in reversed(messages):
        message_type = str(message.get("type") or "")
        content = str(message.get("content") or "").strip()
        if not content or message_type == SESSION_SUMMARY_TYPE:
            continue

        if not found_latest_user:
            if message_type == "chat_user" and content == normalized_user_message:
                found_latest_user = True
            continue

        if message_type in {"agent_response", "chat_assistant"}:
            return content

    return ""
