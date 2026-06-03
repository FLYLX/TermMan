from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import nonebot
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


LOADED_ROBOTS, ROBOT_ID_BY_IDENTITY, IDENTITY_BY_ROBOT_ID, CONFIG_ERRORS = (
    load_runtime_config()
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


def _robot_ws_url(robot_id: str) -> str | None:
    robot = ROBOT_BY_ID.get(robot_id)
    if robot is None:
        return None
    credentials = robot.runtime_config.get("credentials")
    if not isinstance(credentials, dict):
        return None
    value = credentials.get("ws_url")
    if value in (None, ""):
        return None
    return str(value)


def _default_onebot_socket_status(robot_id: str) -> dict[str, Any]:
    status: dict[str, Any] = {"connected": False}
    ws_url = _robot_ws_url(robot_id)
    if ws_url:
        status["server_url"] = ws_url
        status["ws_url"] = ws_url
    return status


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
        "server_url": _robot_ws_url(robot_id),
        "ws_url": _robot_ws_url(robot_id),
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
        },
    )

    try:
        dispatch = await dispatch_to_backend(robot_id, inbound)
    except Exception as exc:
        logger.exception(
            "[RobotBridge] Failed to dispatch message for robot %s", robot_id
        )
        try:
            await send_text_with_rate_limit(
                bot,
                inbound.reply_target,
                f"Robot bridge failed: {exc}",
            )
        except Exception:
            logger.exception(
                "[RobotBridge] Failed to send bridge error back to platform for robot %s",
                robot_id,
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
        await send_text_with_rate_limit(bot, inbound.reply_target, chunk)


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

    def _restart() -> None:
        time.sleep(0.2)
        os._exit(0)

    threading.Thread(target=_restart, daemon=True).start()
    return RobotBridgeReloadResponse(success=True, detail="Bridge restart scheduled")


@app.get("/internal/health")
async def internal_health(
    x_termman_bridge_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _assert_bridge_permission(x_termman_bridge_token)

    checked_at = datetime.now(timezone.utc).isoformat()
    connected_bot_count = len(get_bots())
    connected_bot_identities = _connected_bot_identities()
    connected_identities = [
        identity
        for robot_id, identity in IDENTITY_BY_ROBOT_ID.items()
        if robot_id in SEEN_CONNECTED_ROBOT_IDS or identity in connected_bot_identities
    ]

    robot_status: dict[str, dict[str, Any]] = {}
    for robot_id, identity in IDENTITY_BY_ROBOT_ID.items():
        robot = ROBOT_BY_ID.get(robot_id)
        socket_status = {
            **_default_onebot_socket_status(robot_id),
            **ONEBOT_SOCKET_STATUS_BY_ROBOT_ID.get(robot_id, {}),
        }
        robot_status[robot_id] = {
            "identity": identity,
            "platform": robot.platform if robot else None,
            "ws_url": _robot_ws_url(robot_id),
            "connected": identity in connected_identities,
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
        "robots": robot_status,
        "backend": await check_backend_health(),
        "connection_errors": CONFIG_ERRORS,
    }


def main() -> None:
    logger.info(
        "[RobotBridge] Starting standalone bridge with %d robot(s), platforms=%s",
        len(LOADED_ROBOTS),
        _loaded_robot_platforms(LOADED_ROBOTS),
    )
    nonebot.run(host=settings.ROBOT_BRIDGE_HOST, port=settings.ROBOT_BRIDGE_PORT)


if __name__ == "__main__":
    main()
