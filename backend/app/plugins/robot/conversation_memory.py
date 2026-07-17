from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.core.config import settings

MemoryRole = Literal["user", "assistant", "system"]
DEFAULT_RECENT_LINES = 8
DEFAULT_IMPORT_MAX_BYTES = 2 * 1024 * 1024
UNKNOWN_CONVERSATION_ID = "unknown"
CONVERSATION_ENTRY_RE = re.compile(
    r"^\[[^\]]+\]\s+(?P<role>user|assistant|system)(?:\s+[^:]+)?:\s*(?P<text>.*)$"
)
RECENT_DIALOGUE_SCAN_MIN_LINES = 24
RECENT_DIALOGUE_SCAN_MAX_LINES = 96


def recent_dialogue_scan_lines(lines: int) -> int:
    requested = max(1, int(lines))
    return min(
        RECENT_DIALOGUE_SCAN_MAX_LINES,
        max(RECENT_DIALOGUE_SCAN_MIN_LINES, requested * 4),
    )


def select_recent_dialogue_lines(content: str, *, lines: int) -> list[str]:
    limit = max(1, int(lines))
    candidates = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    if not candidates:
        return []

    deduplicated_reversed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in reversed(candidates):
        match = CONVERSATION_ENTRY_RE.match(line)
        role = match.group("role") if match else ""
        visible_text = match.group("text") if match else line
        normalized_text = re.sub(r"\s+", " ", visible_text).strip().casefold()
        signature = (role, normalized_text)
        if normalized_text and signature in seen:
            continue
        if normalized_text:
            seen.add(signature)
        deduplicated_reversed.append((role, line))

    assistant_limit = max(1, limit // 2)
    assistant_count = 0
    selected_reversed: list[str] = []
    for role, line in deduplicated_reversed:
        if role == "assistant":
            if assistant_count >= assistant_limit:
                continue
            assistant_count += 1
        selected_reversed.append(line)
        if len(selected_reversed) >= limit:
            break
    return list(reversed(selected_reversed))


@dataclass(frozen=True)
class RobotConversationMemoryInfo:
    robot_id: str
    conversation_key: str
    path: str
    exists: bool
    size_bytes: int
    updated_at: str | None


@dataclass(frozen=True)
class RobotConversationMemoryEntry(RobotConversationMemoryInfo):
    filename: str


def normalize_conversation_key(conversation_key: str) -> str:
    normalized = " ".join(str(conversation_key or "").strip().split())
    return normalized or f"group:{UNKNOWN_CONVERSATION_ID}"


def conversation_key_from_target(
    target_type: str,
    target_id: str,
    *,
    fallback: str = "",
) -> str:
    normalized_type = str(target_type or "").strip().lower()
    normalized_id = str(target_id or "").strip()
    if normalized_type in {"private", "c2c", "direct", "direct_message", "friend"}:
        normalized_type = "private"
    elif normalized_type in {"channel", "guild", "guild_channel"}:
        normalized_type = "channel"
    elif normalized_type != "group":
        normalized_type = "group"
    if normalized_id:
        return f"{normalized_type}:{normalized_id}"
    return normalize_conversation_key(fallback)


def conversation_key_from_reply_target(reply_target, sender_key: str = "") -> str:
    if reply_target is None:
        return normalize_conversation_key(sender_key)

    metadata = reply_target.metadata if isinstance(reply_target.metadata, dict) else {}
    conversation = metadata.get("conversation")
    if isinstance(conversation, dict):
        conversation_type = str(
            conversation.get("type")
            or conversation.get("target_type")
            or conversation.get("conversation_type")
            or ""
        ).strip()
        conversation_id = str(
            conversation.get("id")
            or conversation.get("target_id")
            or conversation.get("conversation_id")
            or ""
        ).strip()
        if conversation_type and conversation_id:
            return conversation_key_from_target(
                conversation_type,
                conversation_id,
                fallback=sender_key,
            )

    target_data = metadata.get("target")
    if isinstance(target_data, dict):
        if bool(target_data.get("private")):
            target_type = "private"
        elif bool(target_data.get("channel")):
            target_type = "channel"
        else:
            target_type = str(target_data.get("message_type") or reply_target.target_type)
        target_id = str(
            target_data.get("group_id")
            or target_data.get("user_id")
            or target_data.get("parent_id")
            or target_data.get("id")
            or reply_target.target_id
            or ""
        ).strip()
        if target_id:
            return conversation_key_from_target(target_type, target_id, fallback=sender_key)

    return conversation_key_from_target(
        str(reply_target.target_type or ""),
        str(reply_target.target_id or ""),
        fallback=sender_key,
    )


class RobotConversationMemoryManager:
    def __init__(
        self,
        base_dir: str | Path | None = None,
        *,
        max_bytes: int | None = None,
    ) -> None:
        configured_dir = base_dir or settings.ROBOT_CONVERSATION_MEMORY_DIR
        self.base_dir = Path(configured_dir).expanduser().resolve()
        self.max_bytes = max(
            1024,
            int(max_bytes or settings.ROBOT_CONVERSATION_MEMORY_MAX_BYTES),
        )
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _lock_for_path(self, path: Path) -> threading.Lock:
        key = str(path)
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def _robot_dir(self, robot_id: uuid.UUID | str) -> Path:
        robot_key = self._safe_segment(str(robot_id or "unknown"))
        path = (self.base_dir / robot_key).resolve()
        if not self._is_within_base(path):
            raise ValueError("Invalid robot memory path")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _memory_path(self, robot_id: uuid.UUID | str, conversation_key: str) -> Path:
        normalized_key = normalize_conversation_key(conversation_key)
        filename = f"{self._safe_segment(self._file_label(normalized_key))}.log"
        path = (self._robot_dir(robot_id) / filename).resolve()
        if not self._is_within_base(path):
            raise ValueError("Invalid conversation memory path")
        return path

    def _is_within_base(self, path: Path) -> bool:
        try:
            path.relative_to(self.base_dir)
            return True
        except ValueError:
            return False

    @staticmethod
    def _file_label(conversation_key: str) -> str:
        if ":" not in conversation_key:
            return conversation_key
        conversation_type, conversation_id = conversation_key.split(":", 1)
        label_id = conversation_id or UNKNOWN_CONVERSATION_ID
        if conversation_type == "group":
            return label_id
        return f"{conversation_type}-{label_id}"

    @staticmethod
    def _conversation_key_from_file_label(file_label: str) -> str:
        if file_label.startswith("private-"):
            return conversation_key_from_target(
                "private",
                file_label.removeprefix("private-"),
            )
        if file_label.startswith("channel-"):
            return conversation_key_from_target(
                "channel",
                file_label.removeprefix("channel-"),
            )
        return conversation_key_from_target("group", file_label)

    @staticmethod
    def _safe_segment(value: str) -> str:
        segment = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
        segment = re.sub(r"-{2,}", "-", segment).strip(".-_")
        return segment[:120] or UNKNOWN_CONVERSATION_ID

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sanitize_text(text: str) -> str:
        return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    def _trim_file_locked(self, path: Path) -> None:
        if not path.exists() or path.stat().st_size <= self.max_bytes:
            return
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - self.max_bytes))
            data = file.read()
        marker_index = data.find(b"\n")
        if marker_index > 0:
            data = data[marker_index + 1 :]
        path.write_bytes(data)

    def append_entry(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        *,
        role: MemoryRole,
        text: str,
        sender: str = "",
    ) -> RobotConversationMemoryInfo:
        normalized_text = self._sanitize_text(text)
        if not normalized_text:
            return self.info(robot_id, conversation_key)

        normalized_key = normalize_conversation_key(conversation_key)
        path = self._memory_path(robot_id, normalized_key)
        lock = self._lock_for_path(path)
        sender_label = self._sanitize_text(sender)
        header = f"[{self._timestamp()}] {role}"
        if sender_label:
            header = f"{header} {sender_label}"
        entry = f"{header}: {normalized_text}\n"

        with lock:
            with path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(entry)
            self._trim_file_locked(path)
        return self.info(robot_id, normalized_key)

    def append_user_message(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        text: str,
        *,
        sender: str = "",
    ) -> RobotConversationMemoryInfo:
        return self.append_entry(
            robot_id,
            conversation_key,
            role="user",
            text=text,
            sender=sender,
        )

    def append_assistant_message(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        text: str,
    ) -> RobotConversationMemoryInfo:
        from app.plugins.robot.internal_trace import sanitize_robot_visible_text

        return self.append_entry(
            robot_id,
            conversation_key,
            role="assistant",
            text=sanitize_robot_visible_text(text),
        )

    def read(self, robot_id: uuid.UUID | str, conversation_key: str) -> str:
        path = self._memory_path(robot_id, conversation_key)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def read_recent(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        *,
        lines: int = DEFAULT_RECENT_LINES,
    ) -> str:
        content = self.read(robot_id, conversation_key)
        if not content:
            return ""
        all_lines = content.splitlines()
        return "\n".join(all_lines[-max(1, lines) :])

    def replace(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        content: str,
        *,
        append: bool = False,
        max_import_bytes: int = DEFAULT_IMPORT_MAX_BYTES,
    ) -> RobotConversationMemoryInfo:
        normalized_content = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
        encoded = normalized_content.encode("utf-8")
        if len(encoded) > max_import_bytes:
            raise ValueError(f"Conversation memory import exceeds {max_import_bytes} bytes")
        if normalized_content and not normalized_content.endswith("\n"):
            normalized_content += "\n"

        path = self._memory_path(robot_id, conversation_key)
        lock = self._lock_for_path(path)
        with lock:
            mode = "a" if append else "w"
            with path.open(mode, encoding="utf-8", newline="\n") as file:
                file.write(normalized_content)
            self._trim_file_locked(path)
        return self.info(robot_id, conversation_key)

    def delete(self, robot_id: uuid.UUID | str, conversation_key: str) -> bool:
        path = self._memory_path(robot_id, conversation_key)
        lock = self._lock_for_path(path)
        with lock:
            if not path.exists():
                return False
            path.unlink()
            return True

    def info(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
    ) -> RobotConversationMemoryInfo:
        normalized_key = normalize_conversation_key(conversation_key)
        path = self._memory_path(robot_id, normalized_key)
        exists = path.exists()
        stat = path.stat() if exists else None
        updated_at = (
            datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            if stat is not None
            else None
        )
        return RobotConversationMemoryInfo(
            robot_id=str(robot_id),
            conversation_key=normalized_key,
            path=str(path),
            exists=exists,
            size_bytes=stat.st_size if stat is not None else 0,
            updated_at=updated_at,
        )

    def export_filename(self, conversation_key: str) -> str:
        normalized_key = normalize_conversation_key(conversation_key)
        return f"{self._safe_segment(self._file_label(normalized_key))}.log"

    def list_conversations(
        self,
        robot_id: uuid.UUID | str,
    ) -> list[RobotConversationMemoryEntry]:
        robot_dir = self._robot_dir(robot_id)
        entries: list[RobotConversationMemoryEntry] = []
        for path in robot_dir.glob("*.log"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if not self._is_within_base(resolved):
                continue
            stat = resolved.stat()
            conversation_key = normalize_conversation_key(
                self._conversation_key_from_file_label(resolved.stem)
            )
            entries.append(
                RobotConversationMemoryEntry(
                    robot_id=str(robot_id),
                    conversation_key=conversation_key,
                    path=str(resolved),
                    exists=True,
                    size_bytes=stat.st_size,
                    updated_at=datetime.fromtimestamp(
                        stat.st_mtime,
                        timezone.utc,
                    ).isoformat(),
                    filename=resolved.name,
                )
            )

        entries.sort(key=lambda entry: entry.updated_at or "", reverse=True)
        return entries

    def format_prompt_memory(
        self,
        robot_id: uuid.UUID | str,
        conversation_key: str,
        *,
        lines: int = DEFAULT_RECENT_LINES,
    ) -> str:
        from app.plugins.robot.internal_trace import sanitize_robot_visible_text

        recent = sanitize_robot_visible_text(
            self.read_recent(robot_id, conversation_key, lines=lines)
        ).strip()
        if not recent:
            return ""
        normalized_key = normalize_conversation_key(conversation_key)
        return (
            "Current QQ conversation .log memory "
            f"({normalized_key}, latest {lines} entries only):\n{recent}\n\n"
            "Use this .log as conversation-local memory only. Do not treat it as "
            "messages from other QQ groups or private chats. Old entries are "
            "background context, not new messages waiting for a reply."
        )


robot_conversation_memory = RobotConversationMemoryManager()
