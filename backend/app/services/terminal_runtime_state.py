from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


ACTIVE_TERMINAL_STATUSES = frozenset({"running", "waiting_backend"})


@dataclass(frozen=True)
class TerminalRuntimeState:
    item_id: str
    active: bool = False
    daemon_connected: bool = False
    terminal_process_active: bool = False
    process_status: str = "unknown"
    backend_room_connected: bool = False
    permanent_subscriber_count: int = 0
    reason: str = "unknown"

    def user_message(self) -> str:
        if self.active:
            return (
                "终端已启动并已连接。"
                f"当前状态：{self.process_status}；Backend 已进入对应 Socket Room。"
            )
        reason_messages = {
            "invalid_item_id": "终端 Item ID 无效。",
            "item_not_found": "终端 Item 不存在。",
            "daemon_not_configured": "终端尚未配置 Daemon。",
            "daemon_not_connected": "Backend 与 Daemon 当前没有 Socket 连接。",
            "terminal_status_unavailable": "无法从 Daemon 获取终端实时状态。",
            "terminal_not_running": "终端进程没有启动。",
            "backend_room_not_connected": (
                "终端进程存在，但 Backend 没有进入对应的 Socket Room。"
            ),
        }
        detail = reason_messages.get(self.reason, "终端当前不可用。")
        return f"终端未启动或未连接。{detail}"

    def prompt_context(self) -> str:
        return "\n".join(
            [
                "Authoritative live terminal state (queried now; overrides history and memory):",
                f"- active: {str(self.active).lower()}",
                f"- daemon_connected: {str(self.daemon_connected).lower()}",
                f"- process_status: {self.process_status}",
                f"- backend_room_connected: {str(self.backend_room_connected).lower()}",
                f"- permanent_subscriber_count: {self.permanent_subscriber_count}",
                f"- reason: {self.reason}",
                "Hard rule: never claim the terminal is open unless active=true. "
                "A historical log, Item running flag, cached input handler, or previous chat "
                "is not evidence of a live terminal connection.",
            ]
        )


def _room_state(data: dict[str, Any]) -> tuple[bool, int]:
    room_info = data.get("room_info")
    if not isinstance(room_info, dict):
        return bool(data.get("backend_room_connected")), 0
    try:
        permanent_count = int(room_info.get("permanent_count") or 0)
    except (TypeError, ValueError):
        permanent_count = 0
    if "backend_room_connected" in data:
        connected = bool(data.get("backend_room_connected")) and permanent_count > 0
    else:
        connected = permanent_count > 0
    return connected, permanent_count


def get_terminal_runtime_state(item_id: str) -> TerminalRuntimeState:
    normalized_item_id = str(item_id or "").strip()
    try:
        item_uuid = uuid.UUID(normalized_item_id)
    except (TypeError, ValueError):
        return TerminalRuntimeState(
            item_id=normalized_item_id,
            reason="invalid_item_id",
        )

    from sqlmodel import Session

    from app.core.db import engine
    from app.models import Item
    from app.services import DaemonConfig, connection_manager

    with Session(engine) as db:
        item = db.get(Item, item_uuid)
        if not item:
            return TerminalRuntimeState(
                item_id=normalized_item_id,
                reason="item_not_found",
            )
        if not item.socket_host or not item.socket_port or not item.api_key:
            return TerminalRuntimeState(
                item_id=normalized_item_id,
                reason="daemon_not_configured",
            )
        daemon_config = DaemonConfig(item.socket_host, item.socket_port, item.api_key)

    connection = connection_manager.get_or_create_connection(daemon_config)
    if not connection.is_connected():
        return TerminalRuntimeState(
            item_id=normalized_item_id,
            reason="daemon_not_connected",
        )

    try:
        status_result = connection.terminal_status_http(
            normalized_item_id,
            timeout=5.0,
        )
    except Exception:
        return TerminalRuntimeState(
            item_id=normalized_item_id,
            daemon_connected=True,
            reason="terminal_status_unavailable",
        )
    if not status_result.get("success"):
        return TerminalRuntimeState(
            item_id=normalized_item_id,
            daemon_connected=True,
            reason="terminal_status_unavailable",
        )

    status_data = status_result.get("data") or {}
    process_status = str(status_data.get("status") or "unknown")
    terminal_process_active = process_status in ACTIVE_TERMINAL_STATUSES
    backend_room_connected, permanent_count = _room_state(status_data)

    # Older daemons do not include Room state in terminal/status. Fall back to
    # the dedicated subscriber query so Backend upgrades remain compatible.
    if "room_info" not in status_data and "backend_room_connected" not in status_data:
        try:
            subscriber_result = connection.get_item_subscribers_http(
                normalized_item_id,
                timeout=5.0,
            )
        except Exception:
            subscriber_result = {"success": False}
        if subscriber_result.get("success"):
            backend_room_connected, permanent_count = _room_state(subscriber_result)

    active = terminal_process_active and backend_room_connected
    if not terminal_process_active:
        reason = "terminal_not_running"
    elif not backend_room_connected:
        reason = "backend_room_not_connected"
    else:
        reason = "active"

    return TerminalRuntimeState(
        item_id=normalized_item_id,
        active=active,
        daemon_connected=True,
        terminal_process_active=terminal_process_active,
        process_status=process_status,
        backend_room_connected=backend_room_connected,
        permanent_subscriber_count=permanent_count,
        reason=reason,
    )
