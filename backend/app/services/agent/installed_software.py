from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR

_INSTALLED_SOFTWARE_DIR = BACKEND_DIR.parent / ".runtime" / "installed_software"
_LOCK = threading.RLock()
_SAFE_ITEM_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
MAX_PROMPT_ITEMS = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, *, max_length: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text[:max_length]


def _normalize_name(value: Any) -> str:
    return _clean_text(value, max_length=160)


def _normalize_manager(value: Any) -> str:
    manager = _clean_text(value, max_length=64).lower()
    return manager or "unknown"


def _item_file(item_id: str) -> Path:
    safe_item_id = _SAFE_ITEM_ID_RE.sub("_", str(item_id).strip())
    if not safe_item_id:
        safe_item_id = "unknown"
    return _INSTALLED_SOFTWARE_DIR / f"{safe_item_id}.json"


def _empty_data() -> dict[str, Any]:
    return {"version": 1, "items": []}


def _load_data(item_id: str) -> dict[str, Any]:
    path = _item_file(item_id)
    if not path.exists():
        return _empty_data()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_data()
    if not isinstance(data, dict):
        return _empty_data()
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    data["version"] = 1
    return data


def _save_data(item_id: str, data: dict[str, Any]) -> None:
    path = _item_file(item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def list_installed_software(item_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load_data(item_id)
        items = data.get("items") if isinstance(data.get("items"), list) else []
        normalized: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict) and item.get("name"):
                normalized.append(dict(item))
        return sorted(
            normalized,
            key=lambda item: (
                str(item.get("manager") or ""),
                str(item.get("name") or "").lower(),
            ),
        )


def record_installed_software(
    item_id: str,
    *,
    name: str,
    manager: str = "unknown",
    version: str = "",
    command: str = "",
    notes: str = "",
) -> dict[str, Any]:
    clean_name = _normalize_name(name)
    if not clean_name:
        raise ValueError("software name is required")

    clean_manager = _normalize_manager(manager)
    clean_version = _clean_text(version, max_length=120)
    clean_command = _clean_text(command, max_length=500)
    clean_notes = _clean_text(notes, max_length=500)
    now = _now_iso()

    with _LOCK:
        data = _load_data(item_id)
        items = data.setdefault("items", [])
        if not isinstance(items, list):
            items = []
            data["items"] = items

        matched: dict[str, Any] | None = None
        for existing in items:
            if not isinstance(existing, dict):
                continue
            if (
                str(existing.get("name") or "").lower() == clean_name.lower()
                and _normalize_manager(existing.get("manager")) == clean_manager
            ):
                matched = existing
                break

        if matched is None:
            matched = {
                "name": clean_name,
                "manager": clean_manager,
                "installed_at": now,
            }
            items.append(matched)

        matched.update(
            {
                "name": clean_name,
                "manager": clean_manager,
                "updated_at": now,
            }
        )
        if clean_version:
            matched["version"] = clean_version
        elif "version" not in matched:
            matched["version"] = "unknown"
        if clean_command:
            matched["command"] = clean_command
        if clean_notes:
            matched["notes"] = clean_notes

        _save_data(item_id, data)
        return dict(matched)


def remove_installed_software(
    item_id: str,
    *,
    name: str,
    manager: str = "",
    reason: str = "",
) -> dict[str, Any]:
    clean_name = _normalize_name(name)
    if not clean_name:
        raise ValueError("software name is required")
    clean_manager = _normalize_manager(manager) if manager else ""

    with _LOCK:
        data = _load_data(item_id)
        items = data.get("items") if isinstance(data.get("items"), list) else []
        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for existing in items:
            if not isinstance(existing, dict):
                continue
            same_name = str(existing.get("name") or "").lower() == clean_name.lower()
            same_manager = not clean_manager or _normalize_manager(existing.get("manager")) == clean_manager
            if same_name and same_manager:
                removed.append(dict(existing))
            else:
                kept.append(existing)

        data["items"] = kept
        data["last_removed_at"] = _now_iso()
        if reason_text := _clean_text(reason, max_length=500):
            data["last_remove_reason"] = reason_text
        _save_data(item_id, data)
        return {"removed": removed, "count": len(removed)}


def format_installed_software(items: list[dict[str, Any]], *, limit: int = MAX_PROMPT_ITEMS) -> str:
    if not items:
        return "none recorded"
    lines: list[str] = []
    for item in items[:limit]:
        name = _clean_text(item.get("name"), max_length=160) or "unknown"
        manager = _normalize_manager(item.get("manager"))
        version = _clean_text(item.get("version"), max_length=120) or "unknown"
        notes = _clean_text(item.get("notes"), max_length=160)
        line = f"- {name} [{manager}], version={version}"
        if notes:
            line += f", notes={notes}"
        lines.append(line)
    if len(items) > limit:
        lines.append(f"- ... {len(items) - limit} more recorded item(s)")
    return "\n".join(lines)


def build_installed_software_prompt(item_id: str) -> str:
    items = list_installed_software(item_id)
    return (
        "Current installed software list for this terminal item:\n"
        f"{format_installed_software(items)}\n"
        "Rules: This list is a recorded cache, not proof of absence. Before installing, "
        "check this list first; if the requested software is listed, verify version/path "
        "before reinstalling. If it is not listed, run one local existence check before "
        "installing when practical. After a successful install or uninstall is confirmed "
        "from terminal output, update this list with the installed-software MCP tools."
    )