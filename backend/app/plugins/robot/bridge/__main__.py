from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import nonebot
from fastapi import FastAPI, Header, HTTPException
from nonebot import get_asgi, get_bots, on, on_message
from nonebot.adapters import Bot, Event
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import Robot
from app.plugins.robot.contracts import (
    RobotBridgeReloadResponse,
    RobotBridgeSendRequest,
    RobotDispatchResponse,
    RobotInboundMessage,
)
from app.plugins.robot.debug_log import preview_text, record_robot_event
from app.plugins.robot.bridge.rate_limit import send_text_with_rate_limit
from app.plugins.robot.platforms import (
    build_inbound_message,
    build_nonebot_init_kwargs,
    get_robot_platform,
    get_robot_runtime_config,
    normalize_robot_platform_id,
    register_nonebot_adapters,
    resolve_bot_identity,
    resolve_platform_from_bot,
    resolve_robot_identity,
)

logger = logging.getLogger(__name__)


def _load_enabled_robot_configs() -> tuple[list[Robot], dict[str, str], dict[str, str]]:
    loaded_robots: list[Robot] = []
    robot_id_by_identity: dict[str, str] = {}
    identity_by_robot_id: dict[str, str] = {}

    with Session(engine) as session:
        robots = session.exec(
            select(Robot).where(
                Robot.is_enabled == True,  # noqa: E712
                Robot.provider == "nonebot2",
            )
        ).all()

    for robot in robots:
        platform_id = normalize_robot_platform_id(robot.platform or robot.protocol)
        try:
            get_robot_platform(platform_id)
            get_robot_runtime_config(robot)
            identity = resolve_robot_identity(platform_id, robot)
        except Exception as exc:
            logger.warning(
                "[RobotBridge] Skip robot %s because runtime config is invalid: %s",
                robot.id,
                exc,
            )
            continue

        if identity in robot_id_by_identity:
            logger.warning(
                "[RobotBridge] Duplicate robot identity %s detected, keep first robot only",
                identity,
            )
            continue

        loaded_robots.append(robot)
        robot_id_by_identity[identity] = str(robot.id)
        identity_by_robot_id[str(robot.id)] = identity

    return loaded_robots, robot_id_by_identity, identity_by_robot_id


LOADED_ROBOTS, ROBOT_ID_BY_IDENTITY, IDENTITY_BY_ROBOT_ID = _load_enabled_robot_configs()
SEEN_CONNECTED_ROBOT_IDS: set[str] = set()

INIT_KWARGS = build_nonebot_init_kwargs(LOADED_ROBOTS)
INIT_KWARGS.setdefault("driver", "~fastapi+~httpx+~websockets")

nonebot.init(**INIT_KWARGS)
driver = nonebot.get_driver()
register_nonebot_adapters(driver, LOADED_ROBOTS)

event_probe = on(priority=1, block=False)
bridge = on_message(priority=10, block=False)


def _assert_bridge_permission(header_value: str | None) -> None:
    expected = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY
    if not expected or header_value != expected:
        raise HTTPException(status_code=403, detail="Invalid robot bridge token")


def _record_bridge_event(
    robot_id: str,
    *,
    direction: str,
    event: str,
    status: str = "ok",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    record_robot_event(
        robot_id,
        direction=direction,
        event=event,
        status=status,
        message=message,
        payload=payload,
    )
    try:
        shared_secret = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY
        with httpx.Client(timeout=1.5) as client:
            client.post(
                f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
                f"{settings.API_V1_STR}/robots/{robot_id}/debug-events",
                headers={
                    "Content-Type": "application/json",
                    "X-TermMan-Bridge-Token": shared_secret,
                },
                json={
                    "direction": direction,
                    "event": event,
                    "status": status,
                    "message": message,
                    "payload": payload or {},
                },
            )
    except Exception:
        pass


async def _dispatch_to_backend(
    robot_id: str,
    payload: RobotInboundMessage,
) -> RobotDispatchResponse:
    shared_secret = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
            f"{settings.API_V1_STR}/robots/{robot_id}/dispatch",
            headers={"X-TermMan-Bridge-Token": shared_secret},
            content=payload.model_dump_json(),
        )
        response.raise_for_status()
        return RobotDispatchResponse.model_validate(response.json())


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
    _record_bridge_event(
        robot_id,
        direction="platform_to_bridge",
        event="platform_event",
        message=event.__class__.__name__,
        payload={
            "platform": platform_id,
            "bot_identity": bot_identity,
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
            "[RobotBridge] No TermMan robot is mapped to identity %s",
            bot_identity,
        )
        return

    SEEN_CONNECTED_ROBOT_IDS.add(robot_id)
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
        dispatch = await _dispatch_to_backend(robot_id, inbound)
    except Exception as exc:
        logger.exception("[RobotBridge] Failed to dispatch message for robot %s", robot_id)
        try:
            await send_text_with_rate_limit(
                bot,
                inbound.reply_target,
                f"Robot bridge failed: {exc}",
                robot_id=robot_id,
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
        await send_text_with_rate_limit(bot, inbound.reply_target, chunk, robot_id=robot_id)


app = get_asgi()
if not isinstance(app, FastAPI):
    raise RuntimeError("NoneBot ASGI app is not a FastAPI instance")


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

    await send_text_with_rate_limit(bot, body.target, body.text, robot_id=robot_id)
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
async def internal_health() -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    connected_bot_count = len(get_bots())
    connected_identities = [
        identity
        for robot_id, identity in IDENTITY_BY_ROBOT_ID.items()
        if robot_id in SEEN_CONNECTED_ROBOT_IDS or connected_bot_count > 0
    ]

    robot_status: dict[str, dict[str, Any]] = {}
    for robot_id, identity in IDENTITY_BY_ROBOT_ID.items():
        robot_status[robot_id] = {
            "identity": identity,
            "connected": identity in connected_identities,
        }

    backend_status: dict[str, Any] = {"reachable": False}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.ROBOT_BACKEND_URL.rstrip('/')}{settings.API_V1_STR}/utils/health",
            )
            backend_status = {
                "reachable": resp.status_code == 200,
                "status_code": resp.status_code,
            }
    except Exception as exc:
        backend_status["error"] = str(exc)

    return {
        "checked_at": checked_at,
        "live": True,
        "loaded_robot_count": len(IDENTITY_BY_ROBOT_ID),
        "connected_bot_count": connected_bot_count,
        "platforms": sorted(
            {
                normalize_robot_platform_id(robot.platform or robot.protocol)
                for robot in LOADED_ROBOTS
            }
        ),
        "connected_identities": connected_identities,
        "robots": robot_status,
        "backend": backend_status,
    }


def main() -> None:
    nonebot.run(host=settings.ROBOT_BRIDGE_HOST, port=settings.ROBOT_BRIDGE_PORT)


if __name__ == "__main__":
    main()
