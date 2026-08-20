"""
Daemon connection bootstrap and runtime state synchronization.

This module keeps backend-side daemon connectivity aligned with the real daemon
terminal state so backend restarts can recover running item sessions instead of
marking everything as stopped.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.core.db import engine
from app.models import Item, ItemStatus
from app.services.connection_pool import (
    ConnectionManager,
    DaemonConfig,
    backend_conn_pool,
)
from app.services.socket_pool import SocketManager, SocketPoolFacade
from app.services.terminal_service import TerminalService

logger = logging.getLogger(__name__)

ACTIVE_TERMINAL_STATUSES = {"starting", "waiting_backend", "running"}
TERMINAL_STATUS_TO_ITEM_STATUS = {
    "starting": ItemStatus.starting,
    "waiting_backend": ItemStatus.starting,
    "running": ItemStatus.running,
    "stopping": ItemStatus.stopping,
    "stopped": ItemStatus.stopped,
    "error": ItemStatus.error,
}

connection_manager = ConnectionManager()
socket_manager = SocketManager()
socket_pool_facade = SocketPoolFacade(socket_manager=socket_manager)

def _user_tmp_dir() -> Path:
    base = Path(tempfile.gettempdir())
    if os.name == "nt":
        return base
    # /tmp is shared and tmpfs can race on concurrent creation; keep per-user.
    per_user = base / f"termpaws-{os.getuid()}"
    per_user.mkdir(mode=0o700, exist_ok=True)
    return per_user


_initializer_lock_path = str(_user_tmp_dir() / "TermPaws_daemon_initializer.lock")
_initializer_lock_file: Any | None = None
_initializer_lock_owner = False


def _acquire_initializer_lock() -> bool:
    global _initializer_lock_file, _initializer_lock_owner
    if _initializer_lock_owner:
        return True

    try:
        Path(_initializer_lock_path).parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(_initializer_lock_path, "a+")
    except OSError as exc:
        logger.warning(
            "[DaemonInit] Cannot open lock file %s: %s; skip initializer",
            _initializer_lock_path,
            exc,
        )
        return False
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return False

    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    _initializer_lock_file = lock_file
    _initializer_lock_owner = True
    return True


def _build_daemon_key(host: str, port: int, api_key: str) -> str:
    return f"{host}:{port}:{api_key}"


def _map_terminal_status(status: str | None) -> ItemStatus:
    if not status:
        return ItemStatus.stopped
    return TERMINAL_STATUS_TO_ITEM_STATUS.get(status, ItemStatus.stopped)


def _is_active_terminal(status: str | None) -> bool:
    return status in ACTIVE_TERMINAL_STATUSES


def _load_all_items() -> list[Item]:
    with Session(engine) as session:
        return list(session.exec(select(Item)).all())


def _load_items_for_daemon_config(daemon_config: DaemonConfig) -> list[Item]:
    with Session(engine) as session:
        statement = select(Item).where(
            Item.socket_host == daemon_config.ip,
            Item.socket_port == daemon_config.port,
            Item.api_key == daemon_config.api_key,
        )
        return list(session.exec(statement).all())


def _group_items_by_daemon(items: Iterable[Item]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not item.socket_host or not item.socket_port or not item.api_key:
            continue

        key = _build_daemon_key(item.socket_host, item.socket_port, item.api_key)
        if key not in grouped:
            grouped[key] = {
                "config": DaemonConfig(
                    ip=item.socket_host,
                    port=item.socket_port,
                    api_key=item.api_key,
                ),
                "items": [item],
            }
        else:
            grouped[key]["items"].append(item)
    return grouped


def _update_item_socket_connected(item_id: str, connected: bool) -> None:
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            return
        item.socket_connected = connected
        if connected:
            item.socket_last_connected = datetime.now()
        session.add(item)
        session.commit()


def _sync_room_connection_state(item_id: str, room_info: dict[str, Any] | None) -> None:
    connected = bool(room_info and room_info.get("permanent_count", 0) > 0)
    try:
        _update_item_socket_connected(item_id, connected)
    except Exception as exc:
        logger.warning(
            "[Backend] Failed to update room connection state for item %s: %s",
            item_id,
            exc,
        )


def handle_connection_update(data: dict):
    """
    Handle daemon connection pool updates pushed from the daemon main socket.

    This keeps `socket_connected` aligned with the room's backend subscriber
    health while the full terminal status recovery is handled by
    `sync_daemon_connection_state()`.
    """

    update_type = data.get("type")
    rooms = data.get("rooms", {}) or {}

    logger.info(
        "[Backend] Received daemon connection update: type=%s, rooms=%s",
        update_type,
        len(rooms),
    )

    if update_type == "full_sync":
        for item_id, room_info in rooms.items():
            _sync_room_connection_state(item_id, room_info)
        return

    if update_type == "item_update":
        item_id = data.get("item_uuid")
        if item_id:
            _sync_room_connection_state(item_id, data.get("room_info"))


def _fetch_terminal_snapshots(connection: Any, items: list[Item]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}

    try:
        list_result = connection.terminal_list_http()
    except Exception as exc:
        logger.warning("[Backend] terminal/list failed: %s", exc)
        list_result = {"success": False, "error": str(exc)}

    if list_result.get("success"):
        for entry in list_result.get("data", []) or []:
            item_uuid = str(entry.get("item_uuid", "")).strip()
            if item_uuid:
                snapshots[item_uuid] = entry
        return snapshots

    logger.warning(
        "[Backend] Falling back to per-item terminal/status sync: %s",
        list_result.get("error", "terminal/list failed"),
    )

    for item in items:
        item_id = str(item.id)
        try:
            status_result = connection.terminal_status_http(item_id)
        except Exception as exc:
            logger.warning("[Backend] terminal/status failed for %s: %s", item_id, exc)
            continue

        if status_result.get("success") and status_result.get("data"):
            snapshots[item_id] = status_result["data"]

    return snapshots


def _restore_running_terminal_sessions(
    daemon_config: DaemonConfig,
    items: list[Item],
    terminal_snapshots: dict[str, dict[str, Any]],
) -> None:
    terminal_service = TerminalService(connection_manager, socket_pool_facade)
    now = datetime.now()

    with Session(engine) as session:
        for item in items:
            update_item = session.get(Item, item.id)
            if not update_item:
                continue

            snapshot = terminal_snapshots.get(str(item.id))
            if not snapshot:
                update_item.status = ItemStatus.stopped
                update_item.socket_connected = False
                session.add(update_item)
                continue

            terminal_status = snapshot.get("status")
            update_item.status = _map_terminal_status(terminal_status)

            restored = False
            token = snapshot.get("token")
            if token and _is_active_terminal(terminal_status):
                restored = terminal_service.restore_terminal_session(
                    item_uuid=str(update_item.id),
                    owner_uuid=str(update_item.owner_id),
                    daemon_config=daemon_config,
                    token=str(token),
                )

            update_item.socket_connected = restored
            if restored:
                update_item.socket_last_connected = now
            session.add(update_item)

        session.commit()


def _mark_items_disconnected(items: list[Item]) -> None:
    with Session(engine) as session:
        for item in items:
            update_item = session.get(Item, item.id)
            if not update_item:
                continue
            update_item.socket_connected = False
            session.add(update_item)
        session.commit()


def sync_daemon_connection_state(
    daemon_config: DaemonConfig,
    *,
    items: list[Item] | None = None,
) -> bool:
    items_list = items if items is not None else _load_items_for_daemon_config(daemon_config)
    if not items_list:
        return False

    connection = connection_manager.get_or_create_connection(daemon_config)
    connection.on("connection_update", handle_connection_update)

    daemon_state = backend_conn_pool.create_daemon_main_conn_state(
        daemon_config.api_key,
        daemon_config.base_url,
    )

    if not connection.is_connected():
        daemon_state.set_disconnected()
        _mark_items_disconnected(items_list)
        return False

    daemon_state.set_connected()
    terminal_snapshots = _fetch_terminal_snapshots(connection, items_list)
    _restore_running_terminal_sessions(daemon_config, items_list, terminal_snapshots)
    return True


def initialize_daemon_connections():
    """
    Initialize daemon main connections and restore running item state after
    backend startup.
    """

    if not _acquire_initializer_lock():
        logger.warning(
            "Another backend process already owns daemon initialization; "
            "skip startup daemon sync to avoid duplicate backend room subscribers"
        )
        return

    logger.info("Starting up application and initializing daemon connections...")

    try:
        items = _load_all_items()
        logger.info("Found %s items in database", len(items))
    except OperationalError as exc:
        logger.warning("Skipping daemon initialization before database is ready: %s", exc)
        return

    grouped = _group_items_by_daemon(items)
    logger.info("Found %s unique daemon configurations", len(grouped))

    for daemon_key, entry in grouped.items():
        daemon_config: DaemonConfig = entry["config"]
        items_list: list[Item] = entry["items"]

        try:
            synced = sync_daemon_connection_state(daemon_config, items=items_list)
            if synced:
                logger.info("Synchronized daemon state for %s", daemon_key)
            else:
                logger.warning("Daemon %s is not connected", daemon_key)
        except Exception as exc:
            logger.exception("Failed to synchronize daemon %s: %s", daemon_key, exc)
            _mark_items_disconnected(items_list)

    logger.info("Daemon initialization completed")


if __name__ == "__main__":
    initialize_daemon_connections()
