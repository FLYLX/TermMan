from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import nonebot
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from nonebot import get_asgi, get_bots, on, on_message
from nonebot.adapters import Bot, Event

from .backend_client import (
    check_backend_health,
    dispatch_to_backend,
    load_runtime_config,
    record_bridge_event,
)
from .config import settings
from .contracts import (
    RobotBridgeReloadResponse,
    RobotBridgeSendRequest,
    RobotInboundMessage,
)
from .debug_log import preview_text
from .platforms import (
    BridgeRobot,
    build_inbound_message,
    build_nonebot_init_kwargs,
    register_nonebot_adapters,
    resolve_bot_identity,
    resolve_platform_from_bot,
)
from .rate_limit import send_text_with_rate_limit
from .runtime_monitor import collect_runtime_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _load_initial_runtime_config() -> tuple[
    list[BridgeRobot], dict[str, str], dict[str, str], dict[str, str]
]:
    try:
        return load_runtime_config()
    except Exception as exc:
        logger.warning("[RobotBridge] Initial runtime config unavailable: %s", exc)
        return [], {}, {}, {"startup": str(exc)}


LOADED_ROBOTS, ROBOT_ID_BY_IDENTITY, IDENTITY_BY_ROBOT_ID, CONFIG_ERRORS = (
    _load_initial_runtime_config()
)
ROBOT_BY_ID = {robot.id: robot for robot in LOADED_ROBOTS}
SEEN_CONNECTED_ROBOT_IDS: set[str] = set()
LAST_PLATFORM_EVENT_AT_BY_ROBOT_ID: dict[str, str] = {}
LAST_MESSAGE_EVENT_AT_BY_ROBOT_ID: dict[str, str] = {}
ONEBOT_SOCKET_STATUS_BY_ROBOT_ID: dict[str, dict[str, Any]] = {}
ONEBOT_ACTIVE_CONNECTIONS: dict[str, dict[str, Any]] = {}
STALE_ONEBOT_MESSAGE_MAX_AGE_SECONDS = 60.0
STALE_ONEBOT_MESSAGE_FUTURE_GRACE_SECONDS = 900.0
ONEBOT_MESSAGE_TIMEZONE_OFFSET_CANDIDATES_SECONDS = (8 * 3600,)
ROBOT_DISPATCH_QUEUE: asyncio.Queue[RobotDispatchJob] | None = None
ROBOT_DISPATCH_QUEUE_LOOP: asyncio.AbstractEventLoop | None = None
ROBOT_DISPATCH_WORKER_TASKS: list[asyncio.Task[None]] = []


@dataclass(slots=True)
class RobotDispatchJob:
    robot_id: str
    bot: Bot
    inbound: RobotInboundMessage
    enqueued_at: datetime

INIT_KWARGS = build_nonebot_init_kwargs(LOADED_ROBOTS)
INIT_KWARGS.setdefault("driver", "~fastapi+~httpx+~websockets")

nonebot.init(**INIT_KWARGS)
driver = nonebot.get_driver()
register_nonebot_adapters(driver, LOADED_ROBOTS)

event_probe = on(priority=1, block=False)
bridge = on_message(priority=10, block=False)


def _dispatch_queue_max_size() -> int:
    return max(1, settings.ROBOT_BRIDGE_DISPATCH_QUEUE_SIZE)


def _dispatch_worker_count() -> int:
    return max(1, min(settings.ROBOT_BRIDGE_DISPATCH_WORKERS, 16))


def _active_dispatch_worker_count() -> int:
    return len([task for task in ROBOT_DISPATCH_WORKER_TASKS if not task.done()])


def _dispatch_queue_snapshot() -> dict[str, int]:
    queue = ROBOT_DISPATCH_QUEUE
    return {
        "size": queue.qsize() if queue is not None else 0,
        "max_size": _dispatch_queue_max_size(),
        "workers": _active_dispatch_worker_count(),
    }


def _dispatch_failure_payload(inbound: RobotInboundMessage) -> dict[str, str]:
    return {
        "target_type": inbound.reply_target.target_type,
        "target_id": inbound.reply_target.target_id,
    }


def _is_private_reply_target(inbound: RobotInboundMessage) -> bool:
    metadata = inbound.reply_target.metadata
    conversation = metadata.get("conversation")
    if isinstance(conversation, dict):
        conversation_type = str(
            conversation.get("target_type")
            or conversation.get("type")
            or conversation.get("message_type")
            or ""
        ).strip().lower()
        if conversation_type == "private":
            return True

    target_type = str(inbound.reply_target.target_type or "").strip().lower()
    if target_type in {"private", "friend", "user", "direct", "c2c"}:
        return True

    target_data = metadata.get("target")
    return isinstance(target_data, dict) and bool(target_data.get("private"))


def _is_robot_command_text(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized.startswith(("/term ", "/item ", "/terminal ", "/send ", "/write ", "#"))


def _should_notify_dispatch_failure(inbound: RobotInboundMessage) -> bool:
    metadata = inbound.reply_target.metadata
    return bool(
        metadata.get("mentioned_bot")
        or metadata.get("replied_to_bot")
        or _is_private_reply_target(inbound)
        or _is_robot_command_text(inbound.text)
    )


def _ensure_dispatch_workers() -> asyncio.Queue[RobotDispatchJob]:
    global ROBOT_DISPATCH_QUEUE, ROBOT_DISPATCH_QUEUE_LOOP, ROBOT_DISPATCH_WORKER_TASKS

    loop = asyncio.get_running_loop()
    worker_count = _dispatch_worker_count()

    if ROBOT_DISPATCH_QUEUE is None or ROBOT_DISPATCH_QUEUE_LOOP is not loop:
        for task in ROBOT_DISPATCH_WORKER_TASKS:
            task.cancel()
        ROBOT_DISPATCH_QUEUE = asyncio.Queue(maxsize=_dispatch_queue_max_size())
        ROBOT_DISPATCH_QUEUE_LOOP = loop
        ROBOT_DISPATCH_WORKER_TASKS = [
            loop.create_task(
                _dispatch_worker(index),
                name=f"termman-robot-dispatch-worker-{index}",
            )
            for index in range(worker_count)
        ]
        return ROBOT_DISPATCH_QUEUE

    live_tasks = [task for task in ROBOT_DISPATCH_WORKER_TASKS if not task.done()]
    missing_count = worker_count - len(live_tasks)
    if missing_count > 0:
        start_index = len(live_tasks)
        live_tasks.extend(
            loop.create_task(
                _dispatch_worker(start_index + index),
                name=f"termman-robot-dispatch-worker-{start_index + index}",
            )
            for index in range(missing_count)
        )
    ROBOT_DISPATCH_WORKER_TASKS = live_tasks
    return ROBOT_DISPATCH_QUEUE


async def _dispatch_worker(worker_index: int) -> None:
    del worker_index
    while True:
        queue = ROBOT_DISPATCH_QUEUE
        if queue is None:
            await asyncio.sleep(0.2)
            continue

        job = await queue.get()
        try:
            await _process_robot_dispatch_job(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[RobotBridge] Dispatch worker crashed while processing robot %s",
                job.robot_id,
            )
        finally:
            queue.task_done()


async def _enqueue_robot_dispatch(
    robot_id: str,
    bot: Bot,
    inbound: RobotInboundMessage,
) -> bool:
    queue = _ensure_dispatch_workers()
    try:
        queue.put_nowait(
            RobotDispatchJob(
                robot_id=robot_id,
                bot=bot,
                inbound=inbound,
                enqueued_at=datetime.now(timezone.utc),
            )
        )
    except asyncio.QueueFull:
        _record_bridge_event(
            robot_id,
            direction="bridge",
            event="dispatch_dropped_queue_full",
            status="ignored",
            message="Robot bridge dispatch queue is full; message dropped.",
            payload={
                "queue": _dispatch_queue_snapshot(),
                "target_type": inbound.reply_target.target_type,
                "target_id": inbound.reply_target.target_id,
            },
        )
        logger.warning(
            "[RobotBridge] Dispatch queue full; dropped robot=%s target=%s",
            robot_id,
            inbound.reply_target.target_id,
        )
        return False

    _record_bridge_event(
        robot_id,
        direction="bridge_to_backend",
        event="dispatch_queued",
        payload={
            "queue": _dispatch_queue_snapshot(),
            "target_type": inbound.reply_target.target_type,
            "target_id": inbound.reply_target.target_id,
        },
    )
    return True


def _assert_bridge_permission(header_value: str | None) -> None:
    if not settings.bridge_token or header_value != settings.bridge_token:
        raise HTTPException(status_code=403, detail="Invalid robot bridge token")


def _loaded_robot_platforms(robots: list[BridgeRobot]) -> list[str]:
    return sorted({robot.platform for robot in robots})


def _sync_onebot_adapter_config(new_robots: list[BridgeRobot]) -> str | None:
    try:
        new_init_kwargs = build_nonebot_init_kwargs(new_robots)
    except Exception as exc:
        return str(exc)

    adapter = getattr(driver, "_adapters", {}).get("OneBot V11")
    if adapter is None:
        return "OneBot V11 adapter is not loaded"

    onebot_config = getattr(adapter, "onebot_config", None)
    if onebot_config is None:
        return "OneBot V11 adapter config is not available"

    onebot_config.onebot_access_token = new_init_kwargs.get("onebot_access_token")
    onebot_config.onebot_secret = new_init_kwargs.get("onebot_secret")
    return None


def reload_runtime_config() -> RobotBridgeReloadResponse:
    global \
        LOADED_ROBOTS, \
        ROBOT_ID_BY_IDENTITY, \
        IDENTITY_BY_ROBOT_ID, \
        ROBOT_BY_ID, \
        CONFIG_ERRORS

    try:
        (
            new_robots,
            new_robot_id_by_identity,
            new_identity_by_robot_id,
            new_errors,
        ) = load_runtime_config()
    except Exception as exc:
        logger.exception("[RobotBridge] Failed to soft reload runtime config")
        return RobotBridgeReloadResponse(
            success=False,
            detail=f"Bridge soft reload failed: {exc}",
        )

    sync_error = _sync_onebot_adapter_config(new_robots)
    if sync_error is not None:
        return RobotBridgeReloadResponse(
            success=False,
            detail=f"Bridge soft reload failed: {sync_error}",
        )

    old_robot_ids = set(IDENTITY_BY_ROBOT_ID)
    old_identities = set(ROBOT_ID_BY_IDENTITY)
    new_robot_ids = set(new_identity_by_robot_id)
    new_identities = set(new_robot_id_by_identity)
    removed_robot_ids = old_robot_ids - new_robot_ids
    changed_robot_ids = {
        robot_id
        for robot_id in old_robot_ids & new_robot_ids
        if IDENTITY_BY_ROBOT_ID.get(robot_id) != new_identity_by_robot_id.get(robot_id)
    }

    LOADED_ROBOTS = new_robots
    ROBOT_ID_BY_IDENTITY = new_robot_id_by_identity
    IDENTITY_BY_ROBOT_ID = new_identity_by_robot_id
    ROBOT_BY_ID = {robot.id: robot for robot in new_robots}
    CONFIG_ERRORS = new_errors

    stale_robot_ids = removed_robot_ids | changed_robot_ids
    for robot_id in stale_robot_ids:
        SEEN_CONNECTED_ROBOT_IDS.discard(robot_id)
        LAST_PLATFORM_EVENT_AT_BY_ROBOT_ID.pop(robot_id, None)
        LAST_MESSAGE_EVENT_AT_BY_ROBOT_ID.pop(robot_id, None)
        ONEBOT_SOCKET_STATUS_BY_ROBOT_ID.pop(robot_id, None)

    added_robot_count = len(new_robot_ids - old_robot_ids)
    removed_robot_count = len(removed_robot_ids)
    changed_identity_count = len(changed_robot_ids)
    detail = (
        "Bridge runtime config soft reloaded: "
        f"{len(new_robots)} robot(s), "
        f"{added_robot_count} added, "
        f"{removed_robot_count} removed, "
        f"{changed_identity_count} identity changed"
    )
    if old_identities != new_identities:
        logger.info(
            "[RobotBridge] Identity mapping soft reloaded: old=%s new=%s",
            sorted(old_identities),
            sorted(new_identities),
        )
    logger.info("[RobotBridge] %s", detail)
    return RobotBridgeReloadResponse(success=True, detail=detail)


def _onebot_reverse_ws_url() -> str:
    base_url = (settings.ROBOT_BRIDGE_PUBLIC_URL or settings.ROBOT_BRIDGE_URL).rstrip("/")
    parts = urlsplit(base_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    base_path = parts.path.rstrip("/")
    path = f"{base_path}/onebot/v11/ws".replace("//", "/")
    if not path.startswith("/"):
        path = f"/{path}"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


def _default_onebot_socket_status(robot_id: str) -> dict[str, Any]:
    del robot_id
    reverse_ws_url = _onebot_reverse_ws_url()
    return {
        "connected": False,
        "mode": "reverse_websocket",
        "socket_path": "/onebot/v11/ws",
        "reverse_ws_url": reverse_ws_url,
        "ws_url": reverse_ws_url,
    }


def _connected_bot_identities() -> set[str]:
    identities: set[str] = set()
    for bot in get_bots().values():
        try:
            identities.add(resolve_bot_identity(bot))
        except Exception:
            continue
    return identities


def _serialize_event_payload(event: Event) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        try:
            data = event.model_dump()
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    if hasattr(event, "dict"):
        try:
            data = event.dict()
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _summarize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "self_id",
        "post_type",
        "meta_event_type",
        "message_type",
        "sub_type",
        "user_id",
        "group_id",
        "message_id",
        "raw_message",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            summary[key] = value
    return summary


def _is_onebot_heartbeat_payload(payload: dict[str, Any]) -> bool:
    return (
        str(payload.get("post_type") or "").strip().lower() == "meta_event"
        and str(payload.get("meta_event_type") or "").strip().lower() == "heartbeat"
    )


def _coerce_unix_event_time(value: Any) -> float | None:
    try:
        event_time = float(value)
    except (TypeError, ValueError):
        return None
    if event_time <= 0:
        return None
    if event_time > 10_000_000_000:
        event_time = event_time / 1000
    return event_time


def _onebot_event_time(event: Event, payload: dict[str, Any]) -> float | None:
    event_time = _coerce_unix_event_time(payload.get("time"))
    if event_time is not None:
        return event_time
    return _coerce_unix_event_time(getattr(event, "time", None))


def _stale_onebot_message_event_payload(
    event: Event,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if str(payload.get("post_type") or "").strip().lower() != "message":
        return None
    event_time = _onebot_event_time(event, payload)
    if event_time is None:
        return None

    received_at = time.time()
    event_age_seconds = received_at - event_time
    age_candidates = [(event_age_seconds, 0)]
    age_candidates.extend(
        (event_age_seconds - offset_seconds, offset_seconds)
        for offset_seconds in ONEBOT_MESSAGE_TIMEZONE_OFFSET_CANDIDATES_SECONDS
    )

    for adjusted_age_seconds, _offset_seconds in age_candidates:
        if (
            -STALE_ONEBOT_MESSAGE_FUTURE_GRACE_SECONDS
            <= adjusted_age_seconds
            <= STALE_ONEBOT_MESSAGE_MAX_AGE_SECONDS
        ):
            return None

    adjusted_age_seconds, timezone_offset_seconds = min(
        age_candidates,
        key=lambda candidate: abs(candidate[0]),
    )
    return {
        "event_time": event_time,
        "received_at": received_at,
        "event_age_seconds": event_age_seconds,
        "adjusted_event_age_seconds": adjusted_age_seconds,
        "timezone_offset_seconds": timezone_offset_seconds,
        "max_age_seconds": STALE_ONEBOT_MESSAGE_MAX_AGE_SECONDS,
        "future_grace_seconds": STALE_ONEBOT_MESSAGE_FUTURE_GRACE_SECONDS,
        "event_summary": _summarize_event_payload(payload),
    }

def _is_onebot_websocket_scope(scope: dict[str, Any]) -> bool:
    if scope.get("type") != "websocket":
        return False
    return str(scope.get("path") or "").rstrip("/") == "/onebot/v11/ws"


def _decode_websocket_body(message: dict[str, Any]) -> tuple[str | None, int | None]:
    text = message.get("text")
    if isinstance(text, str):
        return text, None

    body = message.get("bytes")
    if isinstance(body, bytes):
        try:
            return body.decode("utf-8"), len(body)
        except UnicodeDecodeError:
            return None, len(body)

    return None, None


def _summarize_websocket_message(
    message: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    text, byte_length = _decode_websocket_body(message)
    payload: dict[str, Any] = {"asgi_type": message.get("type")}
    if byte_length is not None:
        payload["bytes_length"] = byte_length
    if text is not None:
        payload["text_preview"] = preview_text(text)
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, dict):
            params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
            for key, value in {
                "self_id": raw.get("self_id") or params.get("self_id"),
                "post_type": raw.get("post_type"),
                "meta_event_type": raw.get("meta_event_type"),
                "message_type": raw.get("message_type"),
                "sub_type": raw.get("sub_type"),
                "user_id": raw.get("user_id"),
                "group_id": raw.get("group_id"),
                "message_id": raw.get("message_id"),
                "raw_message": raw.get("raw_message"),
                "action": raw.get("action"),
                "echo": raw.get("echo"),
                "status": raw.get("status"),
                "retcode": raw.get("retcode"),
                "interval": raw.get("interval"),
            }.items():
                if value not in (None, ""):
                    payload[key] = value
    if message.get("code") is not None:
        payload["code"] = message.get("code")
    if message.get("reason"):
        payload["reason"] = message.get("reason")
    return text, payload


def _resolve_onebot_socket_identity(
    message: dict[str, Any],
) -> tuple[str | None, str | None]:
    text, _ = _decode_websocket_body(message)
    if not text:
        return None, None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(raw, dict):
        return None, None
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    self_id = raw.get("self_id") or params.get("self_id")
    if self_id is None:
        return None, None
    normalized_self_id = str(self_id).strip()
    robot_id = ROBOT_ID_BY_IDENTITY.get(f"onebot_v11:{normalized_self_id}")
    return robot_id, normalized_self_id


def _websocket_scope_payload(
    scope: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    client = scope.get("client")
    client_text = None
    if isinstance(client, (list, tuple)) and len(client) >= 2:
        client_text = f"{client[0]}:{client[1]}"
    return {
        "connection_id": connection_id,
        "socket_path": scope.get("path"),
        "client": client_text,
    }


def _active_onebot_clients(robot_id: str | None = None) -> list[dict[str, Any]]:
    clients: list[dict[str, Any]] = []
    for connection in ONEBOT_ACTIVE_CONNECTIONS.values():
        if robot_id is not None and connection.get("robot_id") != robot_id:
            continue
        clients.append(
            {
                key: value
                for key, value in connection.items()
                if key
                in {
                    "connection_id",
                    "robot_id",
                    "identity",
                    "self_id",
                    "client",
                    "socket_path",
                    "connected_at",
                    "last_event_at",
                    "event",
                    "direction",
                }
                and value not in (None, "")
            }
        )
    return sorted(
        clients,
        key=lambda item: str(item.get("connected_at") or item.get("connection_id")),
    )


def _active_onebot_client_count(robot_id: str | None = None) -> int:
    return len(_active_onebot_clients(robot_id))


def _serialize_bot_snapshot(bot: Bot) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "self_id": str(getattr(bot, "self_id", "") or ""),
        "adapter": None,
        "class": bot.__class__.__name__,
    }
    try:
        snapshot["adapter"] = str(bot.adapter.get_name())
    except Exception:
        snapshot["adapter"] = None

    bot_info = getattr(bot, "bot_info", None)
    if bot_info is not None:
        snapshot["bot_info"] = {
            key: value
            for key, value in {
                "id": getattr(bot_info, "id", None),
                "username": getattr(bot_info, "username", None),
                "name": getattr(bot_info, "name", None),
            }.items()
            if value is not None
        }
    return snapshot


def _robot_ids_for_platform(platform_id: str) -> list[str]:
    return [robot.id for robot in LOADED_ROBOTS if robot.platform == platform_id]


def _record_loaded_robot_event(
    robot_ids: list[str],
    *,
    direction: str,
    event: str,
    status: str = "ok",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    for robot_id in robot_ids:
        _record_bridge_event(
            robot_id,
            direction=direction,
            event=event,
            status=status,
            message=message,
            payload=payload,
        )


def _record_bridge_event(
    robot_id: str,
    *,
    direction: str,
    event: str,
    status: str = "ok",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    LAST_PLATFORM_EVENT_AT_BY_ROBOT_ID[robot_id] = timestamp
    if event == "platform_message":
        LAST_MESSAGE_EVENT_AT_BY_ROBOT_ID[robot_id] = timestamp
    record_bridge_event(
        robot_id,
        direction=direction,
        event=event,
        status=status,
        message=message,
        payload=payload,
    )


def _record_onebot_websocket_event(
    robot_id: str | None,
    *,
    direction: str,
    event: str,
    status: str = "ok",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if robot_id:
        robot_ids = [robot_id]
    else:
        robot_ids = _robot_ids_for_platform("onebot_v11")
    _record_loaded_robot_event(
        robot_ids,
        direction=direction,
        event=event,
        status=status,
        message=message,
        payload=payload,
    )


def _upsert_onebot_connection(
    connection_id: str,
    state: dict[str, Any],
    *,
    event: str,
    direction: str,
    payload: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    robot_id = state.get("robot_id")
    self_id = state.get("self_id")
    existing = ONEBOT_ACTIVE_CONNECTIONS.get(connection_id, {})
    ONEBOT_ACTIVE_CONNECTIONS[connection_id] = {
        **existing,
        "connection_id": connection_id,
        "robot_id": robot_id,
        "identity": f"onebot_v11:{self_id}" if self_id else None,
        "self_id": self_id,
        "client": payload.get("client"),
        "socket_path": payload.get("socket_path"),
        "connected_at": existing.get("connected_at") or now,
        "last_event_at": now,
        "event": event,
        "direction": direction,
    }


def _drop_onebot_connection(connection_id: str) -> None:
    ONEBOT_ACTIVE_CONNECTIONS.pop(connection_id, None)


def _update_onebot_socket_status(
    robot_id: str,
    *,
    event_name: str,
    payload: dict[str, Any],
    connected: bool = True,
    direction: str | None = None,
) -> None:
    status_payload: dict[str, Any] = {}
    for key in (
        "connection_id",
        "socket_path",
        "client",
        "self_id",
        "post_type",
        "meta_event_type",
        "message_type",
        "sub_type",
        "user_id",
        "group_id",
        "message_id",
        "raw_message",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            status_payload[key] = value

    clients = _active_onebot_clients(robot_id)
    actual_connected = connected or bool(clients)
    ONEBOT_SOCKET_STATUS_BY_ROBOT_ID[robot_id] = {
        **ONEBOT_SOCKET_STATUS_BY_ROBOT_ID.get(robot_id, {}),
        **status_payload,
        "connected": actual_connected,
        "event": event_name,
        "mode": "reverse_websocket",
        "socket_path": "/onebot/v11/ws",
        "reverse_ws_url": _onebot_reverse_ws_url(),
        "ws_url": _onebot_reverse_ws_url(),
        "client_count": len(clients),
        "clients": clients,
        "last_event_at": datetime.now(timezone.utc).isoformat(),
    }
    if direction:
        ONEBOT_SOCKET_STATUS_BY_ROBOT_ID[robot_id]["direction"] = direction
    if actual_connected:
        SEEN_CONNECTED_ROBOT_IDS.add(robot_id)
    else:
        SEEN_CONNECTED_ROBOT_IDS.discard(robot_id)


def _onebot_websocket_event_name(direction: str, asgi_type: str) -> str:
    if direction == "platform_to_bridge":
        return {
            "websocket.connect": "websocket_connect",
            "websocket.receive": "websocket_receive",
            "websocket.disconnect": "websocket_disconnect",
        }.get(asgi_type, "websocket_receive")
    return {
        "websocket.accept": "websocket_accept",
        "websocket.send": "websocket_send",
        "websocket.close": "websocket_close",
    }.get(asgi_type, "websocket_send")


def _is_onebot_websocket_closed_event(event_name: str) -> bool:
    return event_name in {"websocket_disconnect", "websocket_close", "websocket_closed"}


def _should_record_onebot_websocket_event(
    event_name: str,
    payload: dict[str, Any],
) -> bool:
    if event_name in {
        "websocket_connect",
        "websocket_accept",
        "websocket_disconnect",
        "websocket_close",
        "websocket_closed",
        "websocket_error",
    }:
        return True

    if payload.get("post_type") == "message":
        return True

    meta_event_type = str(payload.get("meta_event_type") or "").strip().lower()
    if meta_event_type and meta_event_type != "heartbeat":
        return True

    retcode = payload.get("retcode")
    if retcode not in (None, 0, "0"):
        return True

    action = str(payload.get("action") or "")
    return action.startswith("send_")


def _track_onebot_websocket_message(
    connection_id: str,
    state: dict[str, Any],
    *,
    direction: str,
    raw_message: dict[str, Any],
    connection_payload: dict[str, Any],
) -> None:
    resolved_robot_id, self_id = _resolve_onebot_socket_identity(raw_message)
    if resolved_robot_id:
        state["robot_id"] = resolved_robot_id
    if self_id:
        state["self_id"] = self_id

    text, payload = _summarize_websocket_message(raw_message)
    payload.update(connection_payload)
    asgi_type = str(raw_message.get("type") or "")
    event_name = _onebot_websocket_event_name(direction, asgi_type)
    connected = not _is_onebot_websocket_closed_event(event_name)

    if connected:
        _upsert_onebot_connection(
            connection_id,
            state,
            event=event_name,
            direction=direction,
            payload=payload,
        )
    else:
        state["closed"] = True
        _drop_onebot_connection(connection_id)

    robot_id = state.get("robot_id")
    if robot_id:
        _update_onebot_socket_status(
            robot_id,
            connected=connected,
            event_name=event_name,
            direction=direction,
            payload=payload,
        )

    if _should_record_onebot_websocket_event(event_name, payload):
        _record_onebot_websocket_event(
            robot_id,
            direction=direction,
            event=event_name,
            message=preview_text(text) if text else None,
            payload=payload,
        )


def _close_tracked_onebot_connection(
    connection_id: str,
    state: dict[str, Any],
    connection_payload: dict[str, Any],
) -> None:
    if state.get("closed"):
        return
    state["closed"] = True
    _drop_onebot_connection(connection_id)
    robot_id = state.get("robot_id")
    if robot_id:
        _update_onebot_socket_status(
            robot_id,
            connected=False,
            event_name="websocket_closed",
            direction="platform_to_bridge",
            payload=connection_payload,
        )
    _record_onebot_websocket_event(
        robot_id,
        direction="platform_to_bridge",
        event="websocket_closed",
        payload=connection_payload,
    )


class OneBotWebSocketConnectionTracker:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not _is_onebot_websocket_scope(scope):
            await self.app(scope, receive, send)
            return

        connection_id = uuid.uuid4().hex
        connection_payload = _websocket_scope_payload(scope, connection_id)
        state: dict[str, Any] = {"robot_id": None, "self_id": None, "closed": False}

        async def tracked_receive() -> dict[str, Any]:
            raw_message = await receive()
            _track_onebot_websocket_message(
                connection_id,
                state,
                direction="platform_to_bridge",
                raw_message=raw_message,
                connection_payload=connection_payload,
            )
            return raw_message

        async def tracked_send(raw_message: dict[str, Any]) -> None:
            _track_onebot_websocket_message(
                connection_id,
                state,
                direction="bridge_to_platform",
                raw_message=raw_message,
                connection_payload=connection_payload,
            )
            await send(raw_message)

        try:
            await self.app(scope, tracked_receive, tracked_send)
        except Exception as exc:
            state["closed"] = True
            _drop_onebot_connection(connection_id)
            robot_id = state.get("robot_id")
            if robot_id:
                _update_onebot_socket_status(
                    robot_id,
                    connected=False,
                    event_name="websocket_error",
                    direction="platform_to_bridge",
                    payload=connection_payload,
                )
            _record_onebot_websocket_event(
                robot_id,
                direction="platform_to_bridge",
                event="websocket_error",
                status="error",
                message=str(exc),
                payload=connection_payload,
            )
            raise
        finally:
            _close_tracked_onebot_connection(
                connection_id,
                state,
                connection_payload,
            )


def _resolve_bot_for_robot(robot_id: str) -> Bot | None:
    identity = IDENTITY_BY_ROBOT_ID.get(robot_id)
    if not identity:
        return None

    for bot in get_bots().values():
        try:
            if resolve_bot_identity(bot) == identity:
                return bot
        except Exception:
            continue
    return None


async def _process_robot_dispatch_job(job: RobotDispatchJob) -> None:
    inbound = job.inbound
    queue_wait_seconds = (
        datetime.now(timezone.utc) - job.enqueued_at
    ).total_seconds()
    _record_bridge_event(
        job.robot_id,
        direction="bridge_to_backend",
        event="dispatch_started",
        payload={
            "queue_wait_seconds": round(queue_wait_seconds, 3),
            "queue": _dispatch_queue_snapshot(),
            "target_type": inbound.reply_target.target_type,
            "target_id": inbound.reply_target.target_id,
        },
    )

    try:
        dispatch = await dispatch_to_backend(job.robot_id, inbound)
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        _record_bridge_event(
            job.robot_id,
            direction="bridge_to_backend",
            event="dispatch_failed",
            status="error",
            message=error_message,
        )
        logger.exception(
            "[RobotBridge] Failed to dispatch message for robot %s", job.robot_id
        )
        if not _should_notify_dispatch_failure(inbound):
            _record_bridge_event(
                job.robot_id,
                direction="bridge_to_platform",
                event="dispatch_failure_notification_suppressed",
                status="ignored",
                message=error_message,
                payload=_dispatch_failure_payload(inbound),
            )
            return

        try:
            bot = _resolve_bot_for_robot(job.robot_id) or job.bot
            await send_text_with_rate_limit(
                bot,
                inbound.reply_target,
                f"Backend dispatch failed: {error_message}",
            )
        except Exception as send_exc:
            logger.exception(
                "[RobotBridge] Failed to send dispatch error back to platform "
                "for robot %s: %s",
                job.robot_id,
                send_exc,
            )
        return

    if dispatch.ignored:
        _record_bridge_event(
            job.robot_id,
            direction="bridge_to_backend",
            event="dispatch_ignored",
            status="ignored",
            message=dispatch.reason,
        )
        return

    bot = _resolve_bot_for_robot(job.robot_id) or job.bot
    for chunk in dispatch.reply_chunks:
        logger.info(
            "[RobotBridge] Sending platform reply robot=%s target=%s text=%s",
            job.robot_id,
            inbound.reply_target.target_id,
            preview_text(chunk),
        )
        try:
            await send_text_with_rate_limit(bot, inbound.reply_target, chunk)
        except Exception as send_exc:
            _record_bridge_event(
                job.robot_id,
                direction="bridge_to_platform",
                event="platform_send_failed",
                status="error",
                message=str(send_exc) or send_exc.__class__.__name__,
                payload={
                    "target_type": inbound.reply_target.target_type,
                    "target_id": inbound.reply_target.target_id,
                },
            )
            logger.exception(
                "[RobotBridge] Failed to send platform reply for robot %s",
                job.robot_id,
            )


@event_probe.handle()
async def probe_robot_event(bot: Bot, event: Event) -> None:
    platform_id = resolve_platform_from_bot(bot)
    if not platform_id:
        return

    try:
        bot_identity = resolve_bot_identity(bot)
    except Exception:
        return

    robot_id = ROBOT_ID_BY_IDENTITY.get(bot_identity)
    if not robot_id:
        event_payload = _serialize_event_payload(event)
        _record_loaded_robot_event(
            _robot_ids_for_platform(platform_id),
            direction="platform_to_bridge",
            event="platform_event_unmapped",
            status="error",
            message=event.__class__.__name__,
            payload={
                "platform": platform_id,
                "bot_identity": bot_identity,
                "known_identities": list(ROBOT_ID_BY_IDENTITY.keys()),
                "event_summary": _summarize_event_payload(event_payload),
            },
        )
        return

    SEEN_CONNECTED_ROBOT_IDS.add(robot_id)
    event_payload = _serialize_event_payload(event)
    if platform_id == "onebot_v11":
        _update_onebot_socket_status(
            robot_id,
            event_name=event.__class__.__name__,
            payload=event_payload,
        )
        if _is_onebot_heartbeat_payload(event_payload):
            return
    _record_bridge_event(
        robot_id,
        direction="platform_to_bridge",
        event="platform_event",
        message=event.__class__.__name__,
        payload={
            "platform": platform_id,
            "bot_identity": bot_identity,
            "event_type": event.__class__.__name__,
            "event_summary": _summarize_event_payload(event_payload),
            "event": str(event),
        },
    )


@bridge.handle()
async def handle_robot_message(bot: Bot, event: Event) -> None:
    platform_id = resolve_platform_from_bot(bot)
    if not platform_id:
        return

    try:
        bot_identity = resolve_bot_identity(bot)
    except Exception:
        logger.exception("[RobotBridge] Failed to resolve bot identity")
        return

    robot_id = ROBOT_ID_BY_IDENTITY.get(bot_identity)
    if not robot_id:
        event_payload = _serialize_event_payload(event)
        _record_loaded_robot_event(
            _robot_ids_for_platform(platform_id),
            direction="platform_to_bridge",
            event="event_ignored",
            status="error",
            message=f"No TermMan robot is mapped to identity {bot_identity}",
            payload={
                "platform": platform_id,
                "bot_identity": bot_identity,
                "known_identities": list(ROBOT_ID_BY_IDENTITY.keys()),
                "event_summary": _summarize_event_payload(event_payload),
            },
        )
        logger.warning(
            "[RobotBridge] No TermMan robot is mapped to identity %s", bot_identity
        )
        return

    SEEN_CONNECTED_ROBOT_IDS.add(robot_id)
    event_payload = _serialize_event_payload(event)
    if platform_id == "onebot_v11":
        _update_onebot_socket_status(
            robot_id,
            event_name=event.__class__.__name__,
            payload=event_payload,
        )
        stale_payload = _stale_onebot_message_event_payload(event, event_payload)
        if stale_payload is not None:
            _record_bridge_event(
                robot_id,
                direction="platform_to_bridge",
                event="stale_message_ignored",
                status="ignored",
                message=event.__class__.__name__,
                payload={
                    "platform": platform_id,
                    **stale_payload,
                },
            )
            return
    inbound = build_inbound_message(platform_id, bot, event)
    if inbound is None:
        return
    logger.info(
        "[RobotBridge] Platform message robot=%s sender=%s target=%s text=%s",
        robot_id,
        inbound.sender_key,
        inbound.reply_target.target_id,
        preview_text(inbound.text),
    )
    _record_bridge_event(
        robot_id,
        direction="platform_to_bridge",
        event="platform_message",
        message=inbound.text,
        payload={
            "platform": platform_id,
            "sender_key": inbound.sender_key,
            "target_type": inbound.reply_target.target_type,
            "target_id": inbound.reply_target.target_id,
            "reply_target": inbound.reply_target.model_dump(mode="json"),
            "event_summary": _summarize_event_payload(event_payload),
        },
    )

    await _enqueue_robot_dispatch(robot_id, bot, inbound)


app = get_asgi()
if not isinstance(app, FastAPI):
    raise RuntimeError("NoneBot ASGI app is not a FastAPI instance")


async def shutdown_dispatch_workers() -> None:
    for task in ROBOT_DISPATCH_WORKER_TASKS:
        task.cancel()
    if ROBOT_DISPATCH_WORKER_TASKS:
        await asyncio.gather(*ROBOT_DISPATCH_WORKER_TASKS, return_exceptions=True)


app.router.on_shutdown.append(shutdown_dispatch_workers)


@app.post("/internal/send")
async def internal_send(
    body: RobotBridgeSendRequest,
    x_termman_bridge_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _assert_bridge_permission(x_termman_bridge_token)

    robot_id = str(body.robot_id)
    bot = _resolve_bot_for_robot(robot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Robot is not loaded in bridge")

    payload = {
        "target_type": body.target.target_type,
        "target_id": body.target.target_id,
    }
    _record_bridge_event(
        robot_id,
        direction="bridge_to_platform",
        event="internal_send",
        message=body.text,
        payload=payload,
    )
    try:
        await send_text_with_rate_limit(bot, body.target, body.text)
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        _record_bridge_event(
            robot_id,
            direction="bridge_to_platform",
            event="platform_send_failed",
            status="error",
            message=error_message,
            payload=payload,
        )
        logger.exception(
            "[RobotBridge] Failed to send internal message for robot %s",
            robot_id,
        )
        raise HTTPException(status_code=502, detail=error_message) from exc
    return {"success": True}


@app.post("/internal/reload", response_model=RobotBridgeReloadResponse)
async def internal_reload(
    x_termman_bridge_token: str | None = Header(default=None),
) -> RobotBridgeReloadResponse:
    _assert_bridge_permission(x_termman_bridge_token)
    return await asyncio.to_thread(reload_runtime_config)


@app.get("/internal/health")
async def internal_health(
    x_termman_bridge_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _assert_bridge_permission(x_termman_bridge_token)

    checked_at = datetime.now(timezone.utc).isoformat()
    connected_bot_count = len(get_bots())
    bot_snapshots: list[dict[str, Any]] = []
    bot_snapshot_by_identity: dict[str, dict[str, Any]] = {}
    for bot in get_bots().values():
        snapshot = _serialize_bot_snapshot(bot)
        bot_snapshots.append(snapshot)
        try:
            bot_snapshot_by_identity[resolve_bot_identity(bot)] = snapshot
        except Exception:
            continue
    connected_bot_identities = (
        set(bot_snapshot_by_identity.keys()) or _connected_bot_identities()
    )
    active_onebot_clients = _active_onebot_clients()
    connected_identities = [
        identity
        for robot_id, identity in IDENTITY_BY_ROBOT_ID.items()
        if identity in connected_bot_identities
        or _active_onebot_client_count(robot_id) > 0
    ]

    robot_status: dict[str, dict[str, Any]] = {}
    for robot_id, identity in IDENTITY_BY_ROBOT_ID.items():
        robot = ROBOT_BY_ID.get(robot_id)
        robot_client_count = _active_onebot_client_count(robot_id)
        socket_status = {
            **_default_onebot_socket_status(robot_id),
            **ONEBOT_SOCKET_STATUS_BY_ROBOT_ID.get(robot_id, {}),
        }
        socket_status["client_count"] = robot_client_count
        socket_status["clients"] = _active_onebot_clients(robot_id)
        connected = identity in connected_identities or robot_client_count > 0
        socket_status["connected"] = connected
        if connected:
            socket_status.setdefault("event", "websocket_connected")
        robot_status[robot_id] = {
            "identity": identity,
            "platform": robot.platform if robot else None,
            "reverse_ws_url": _onebot_reverse_ws_url(),
            "ws_url": _onebot_reverse_ws_url(),
            "connected": connected,
            "bot": bot_snapshot_by_identity.get(identity),
            "onebot_socket": socket_status,
            "last_platform_event_at": LAST_PLATFORM_EVENT_AT_BY_ROBOT_ID.get(robot_id),
            "last_message_event_at": LAST_MESSAGE_EVENT_AT_BY_ROBOT_ID.get(robot_id),
        }

    return {
        "checked_at": checked_at,
        "live": True,
        "loaded_robot_count": len(IDENTITY_BY_ROBOT_ID),
        "connected_bot_count": connected_bot_count,
        "onebot_client_count": len(active_onebot_clients),
        "onebot_clients": active_onebot_clients,
        "platforms": _loaded_robot_platforms(LOADED_ROBOTS),
        "connected_identities": connected_identities,
        "onebot_reverse_ws_url": _onebot_reverse_ws_url(),
        "robots": robot_status,
        "bots": bot_snapshots,
        "dispatch_queue": _dispatch_queue_snapshot(),
        "backend": await check_backend_health(),
        "connection_errors": CONFIG_ERRORS,
        "runtime": collect_runtime_stats("robot"),
    }


tracked_app = OneBotWebSocketConnectionTracker(app)


def main() -> None:
    logger.info(
        "[RobotBridge] Starting standalone bridge with %d robot(s), platforms=%s",
        len(LOADED_ROBOTS),
        _loaded_robot_platforms(LOADED_ROBOTS),
    )

    def _run_server() -> None:
        uvicorn.run(
            tracked_app,
            host=settings.ROBOT_BRIDGE_HOST,
            port=settings.ROBOT_BRIDGE_PORT,
            log_level="info",
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _run_server()
        return

    thread = threading.Thread(target=_run_server, daemon=False)
    thread.start()
    thread.join()


if __name__ == "__main__":
    main()
