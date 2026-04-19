from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx
import nonebot
from fastapi import FastAPI, Header, HTTPException
from nonebot import get_asgi, get_bots, on_message
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
    send_text_with_bot,
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

INIT_KWARGS = build_nonebot_init_kwargs(LOADED_ROBOTS)
INIT_KWARGS.setdefault("driver", "~fastapi+~httpx+~websockets")
if any(
    normalize_robot_platform_id(robot.platform or robot.protocol) == "qq_official"
    for robot in LOADED_ROBOTS
):
    INIT_KWARGS["qq_is_sandbox"] = settings.ROBOT_QQ_IS_SANDBOX

nonebot.init(**INIT_KWARGS)
driver = nonebot.get_driver()
register_nonebot_adapters(driver, LOADED_ROBOTS)

bridge = on_message(priority=10, block=False)


def _assert_bridge_permission(header_value: str | None) -> None:
    expected = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY
    if not expected or header_value != expected:
        raise HTTPException(status_code=403, detail="Invalid robot bridge token")


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

    inbound = build_inbound_message(platform_id, bot, event)
    if inbound is None:
        return

    try:
        dispatch = await _dispatch_to_backend(robot_id, inbound)
    except Exception as exc:
        logger.exception("[RobotBridge] Failed to dispatch message for robot %s", robot_id)
        try:
            await send_text_with_bot(bot, inbound.reply_target, f"Robot bridge failed: {exc}")
        except Exception:
            logger.exception(
                "[RobotBridge] Failed to send bridge error back to platform for robot %s",
                robot_id,
            )
        return

    if dispatch.ignored:
        return

    for chunk in dispatch.reply_chunks:
        await send_text_with_bot(bot, inbound.reply_target, chunk)


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

    await send_text_with_bot(bot, body.target, body.text)
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
    return {
        "loaded_robot_count": len(IDENTITY_BY_ROBOT_ID),
        "connected_bot_count": len(get_bots()),
        "platforms": sorted(
            {
                normalize_robot_platform_id(robot.platform or robot.protocol)
                for robot in LOADED_ROBOTS
            }
        ),
    }


def main() -> None:
    nonebot.run(host=settings.ROBOT_BRIDGE_HOST, port=settings.ROBOT_BRIDGE_PORT)


if __name__ == "__main__":
    main()
