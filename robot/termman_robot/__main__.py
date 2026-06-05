from __future__ import annotations

import asyncio
import logging
import threading
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
from .contracts import RobotBridgeReloadResponse, RobotBridgeSendRequest
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

INIT_KWARGS = build_nonebot_init_kwargs(LOADED_ROBOTS)
INIT_KWARGS.setdefault("driver", "~fastapi+~httpx+~websockets")

nonebot.init(**INIT_KWARGS)
driver = nonebot.get_driver()
register_nonebot_adapters(driver, LOADED_ROBOTS)

event_probe = on(priority=1, block=False)
bridge = on_message(priority=10, block=False)


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
    base_url = settings.ROBOT_BRIDGE_URL.rstrip("/")
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


def _update_onebot_socket_status(
    robot_id: str,
    *,
    event_name: str,
    payload: dict[str, Any],
) -> None:
    status_payload: dict[str, Any] = {}
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
            status_payload[key] = value

    ONEBOT_SOCKET_STATUS_BY_ROBOT_ID[robot_id] = {
        **ONEBOT_SOCKET_STATUS_BY_ROBOT_ID.get(robot_id, {}),
        **status_payload,
        "connected": True,
        "event": event_name,
        "mode": "reverse_websocket",
        "socket_path": "/onebot/v11/ws",
        "reverse_ws_url": _onebot_reverse_ws_url(),
        "ws_url": _onebot_reverse_ws_url(),
        "last_event_at": datetime.now(timezone.utc).isoformat(),
    }


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
            "event_summary": _summarize_event_payload(event_payload),
        },
    )

    try:
        dispatch = await dispatch_to_backend(robot_id, inbound)
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        _record_bridge_event(
            robot_id,
            direction="bridge_to_backend",
            event="dispatch_failed",
            status="error",
            message=error_message,
        )
        logger.exception(
            "[RobotBridge] Failed to dispatch message for robot %s", robot_id
        )
        try:
            await send_text_with_rate_limit(
                bot,
                inbound.reply_target,
                f"Backend dispatch failed: {error_message}",
            )
        except Exception as send_exc:
            logger.exception(
                "[RobotBridge] Failed to send dispatch error back to platform "
                "for robot %s: %s",
                robot_id,
                send_exc,
            )
        return

    if dispatch.ignored:
        return

    for chunk in dispatch.reply_chunks:
        logger.info(
            "[RobotBridge] Sending platform reply robot=%s target=%s text=%s",
            robot_id,
            inbound.reply_target.target_id,
            preview_text(chunk),
        )
        try:
            await send_text_with_rate_limit(bot, inbound.reply_target, chunk)
        except Exception as send_exc:
            _record_bridge_event(
                robot_id,
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
                robot_id,
            )


app = get_asgi()
if not isinstance(app, FastAPI):
    raise RuntimeError("NoneBot ASGI app is not a FastAPI instance")


@app.post("/internal/send")
async def internal_send(
    body: RobotBridgeSendRequest,
    x_termman_bridge_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _assert_bridge_permission(x_termman_bridge_token)

    bot = _resolve_bot_for_robot(str(body.robot_id))
    if bot is None:
        raise HTTPException(status_code=404, detail="Robot is not loaded in bridge")

    await send_text_with_rate_limit(bot, body.target, body.text)
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
    connected_identities = [
        identity
        for identity in IDENTITY_BY_ROBOT_ID.values()
        if identity in connected_bot_identities
    ]

    robot_status: dict[str, dict[str, Any]] = {}
    for robot_id, identity in IDENTITY_BY_ROBOT_ID.items():
        robot = ROBOT_BY_ID.get(robot_id)
        socket_status = {
            **_default_onebot_socket_status(robot_id),
            **ONEBOT_SOCKET_STATUS_BY_ROBOT_ID.get(robot_id, {}),
        }
        connected = identity in connected_identities
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
        "platforms": _loaded_robot_platforms(LOADED_ROBOTS),
        "connected_identities": connected_identities,
        "onebot_reverse_ws_url": _onebot_reverse_ws_url(),
        "robots": robot_status,
        "bots": bot_snapshots,
        "backend": await check_backend_health(),
        "connection_errors": CONFIG_ERRORS,
    }


def main() -> None:
    logger.info(
        "[RobotBridge] Starting standalone bridge with %d robot(s), platforms=%s",
        len(LOADED_ROBOTS),
        _loaded_robot_platforms(LOADED_ROBOTS),
    )

    def _run_server() -> None:
        uvicorn.run(
            app,
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
