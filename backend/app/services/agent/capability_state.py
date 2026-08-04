"""Per-item registry of progressively loaded capabilities.

Tools and skill guides are exposed to the agent through a compact catalog.
When the agent calls `mcp_local_prepare_capabilities`, the requested tool
schemas / guide prompts are marked loaded for the item and stay available
for subsequent turns of that item.
"""
from __future__ import annotations

import threading
from typing import Iterable

_LOCK = threading.Lock()
_STATE: dict[str, dict[str, set[str]]] = {}


def _entry(item_id: str) -> dict[str, set[str]]:
    key = str(item_id or "")
    with _LOCK:
        return _STATE.setdefault(key, {"tools": set(), "guides": set()})


def ensure_loaded(item_id: str, *, tools: Iterable[str] = (), guides: Iterable[str] = ()) -> None:
    if not item_id:
        return
    entry = _entry(item_id)
    with _LOCK:
        entry["tools"].update(str(name) for name in tools if str(name).strip())
        entry["guides"].update(str(name) for name in guides if str(name).strip())


def get_loaded_tools(item_id: str) -> frozenset[str]:
    with _LOCK:
        return frozenset(_STATE.get(str(item_id or ""), {}).get("tools", ()))


def get_loaded_guides(item_id: str) -> frozenset[str]:
    with _LOCK:
        return frozenset(_STATE.get(str(item_id or ""), {}).get("guides", ()))


def reset_item(item_id: str) -> None:
    with _LOCK:
        _STATE.pop(str(item_id or ""), None)