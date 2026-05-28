from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException

from app.core.config import settings
from app.plugins.robot.contracts import (
    RobotBridgeReloadResponse,
    RobotBridgeSendRequest,
    RobotDispatchResponse,
    RobotInboundMessage,
)
from app.plugins.robot.debug_log import record_loaded_robot_event, record_robot_event
from app.plugins.robot.bridge.rate_limit import send_text_with_rate_limit
from app.plugins.robot.platforms import (
    build_inbound_message,
    normalize_robot_platform_id,
    resolve_bot_identity,
    resolve_platform_from_bot,
)

logger = logging.getLogger(__name__)

_bridge_router: APIRouter | None = None
_loaded_robots: list = []
_robot_id_by_identity: dict[str, str] = {}
_identity_by_robot_id: dict[str, str] = {}
_seen_connected_robot_ids: set[str] = set()
_initialized = False
_connection_errors: dict[str, dict[str, str]] = {}
_error_file_path: str = "/tmp/robot_bridge_errors.json"
_identity_file_path: str = "/tmp/robot_bridge_identities.json"


def _normalize_connection_errors(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, str]] = {}
    for robot_id, value in raw.items():
        if isinstance(value, dict):
            message = str(value.get("message") or value.get("error") or "")
            timestamp = str(value.get("timestamp") or "")
        else:
            message = str(value)
            timestamp = ""
        if message:
            normalized[str(robot_id)] = {
                "message": message,
                "timestamp": timestamp,
            }
    return normalized


def _load_connection_errors() -> dict[str, dict[str, str]]:
    global _connection_errors
    try:
        import json
        with open(_error_file_path, "r") as f:
            _connection_errors = _normalize_connection_errors(json.load(f))
    except Exception:
        _connection_errors = {}
    return _connection_errors


def _save_connection_error(robot_id: str, error: str) -> None:
    global _connection_errors
    _connection_errors[robot_id] = {
        "message": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        import json
        with open(_error_file_path, "w") as f:
            json.dump(_connection_errors, f)
    except Exception:
        pass


def _save_identities() -> None:
    try:
        import json
        with open(_identity_file_path, "w") as f:
            json.dump(_identity_by_robot_id, f)
    except Exception:
        pass


def _load_identities() -> dict[str, str]:
    try:
        import json
        with open(_identity_file_path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _loguru_sink(message):
    record = message.record
    level = record.get("level")
    level_name = level.name if level else None
    if level_name == "ERROR":
        text = record.get("message", "")
        if "Failed to get gateway info" in text:
            exc_info = record.get("exception")
            identities = _load_identities()
            for robot_id, identity in identities.items():
                if "qq" in identity.lower():
                    exc_text = ""
                    if exc_info:
                        exc_type = exc_info.type if hasattr(exc_info, "type") else None
                        exc_value = exc_info.value if hasattr(exc_info, "value") else None
                        if exc_type and exc_value:
                            exc_text = f"{exc_type.__name__}: {exc_value}"
                    error_msg = exc_text if exc_text else text
                    _save_connection_error(robot_id, error_msg)
                    break


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


def get_bridge_router() -> APIRouter | None:
    global _bridge_router
    return _bridge_router


def get_loaded_robots() -> tuple[list, dict[str, str], dict[str, str]]:
    return _loaded_robots, _robot_id_by_identity, _identity_by_robot_id


def _build_idle_bridge_router(reason: str) -> APIRouter:
    router = APIRouter(prefix="/robot-bridge", tags=["robot-bridge"])

    @router.post("/internal/reload", response_model=RobotBridgeReloadResponse)
    async def internal_reload(
        x_termman_bridge_token: str | None = Header(default=None),
    ) -> RobotBridgeReloadResponse:
        _assert_bridge_permission(x_termman_bridge_token)

        def _restart() -> None:
            time.sleep(0.2)
            os._exit(0)

        threading.Thread(target=_restart, daemon=True).start()
        return RobotBridgeReloadResponse(success=True, detail="Bridge restart scheduled")

        @router.get("/internal/health")
        async def internal_health() -> dict[str, Any]:
            checked_at = datetime.now(timezone.utc).isoformat()
            return {
                "checked_at": checked_at,
                "live": True,
                "status": "idle",
            "reason": reason,
            "loaded_robot_count": 0,
            "connected_bot_count": 0,
            "platforms": [],
            "connected_identities": [],
            "robots": {},
            "backend": {"reachable": True},
            "connection_errors": _load_connection_errors(),
        }

    return router


def init_embedded_bridge() -> APIRouter | None:
    global _bridge_router, _loaded_robots, _robot_id_by_identity, _identity_by_robot_id, _initialized

    if not settings.ROBOT_PLUGIN_ENABLED:
        logger.info("[Bridge] Robot plugin disabled, skip bridge initialization")
        return None

    if _initialized:
        return _bridge_router

    _initialized = True

    try:
        import nonebot
    except ImportError:
        logger.info("[Bridge] nonebot not installed, skip bridge initialization")
        _bridge_router = _build_idle_bridge_router("nonebot_not_installed")
        return _bridge_router

    try:
        from nonebot import get_asgi, get_bots, on_message
        from nonebot.adapters import Bot, Event
        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import Robot
        from app.plugins.robot.platforms import (
            build_nonebot_init_kwargs,
            get_robot_platform,
            get_robot_runtime_config,
            register_nonebot_adapters,
        )

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
                        "[Bridge] Skip robot %s because runtime config is invalid: %s",
                        robot.id,
                        exc,
                    )
                    continue

                if identity in robot_id_by_identity:
                    logger.warning(
                        "[Bridge] Duplicate robot identity %s detected, keep first robot only",
                        identity,
                    )
                    continue

                loaded_robots.append(robot)
                robot_id_by_identity[identity] = str(robot.id)
                identity_by_robot_id[str(robot.id)] = identity

            return loaded_robots, robot_id_by_identity, identity_by_robot_id

        _loaded_robots, _robot_id_by_identity, _identity_by_robot_id = _load_enabled_robot_configs()
        _save_identities()

        if not _loaded_robots:
            logger.info("[Bridge] No enabled robots found, skip bridge initialization")
            _bridge_router = _build_idle_bridge_router("no_enabled_robots")
            return _bridge_router

        init_kwargs = build_nonebot_init_kwargs(_loaded_robots)
        init_kwargs.setdefault("driver", "~fastapi+~httpx+~websockets")
        if any(
            normalize_robot_platform_id(robot.platform or robot.protocol) == "qq_official"
            for robot in _loaded_robots
        ):
            init_kwargs["qq_is_sandbox"] = settings.ROBOT_QQ_IS_SANDBOX

        nonebot.init(**init_kwargs)
        driver = nonebot.get_driver()
        register_nonebot_adapters(driver, _loaded_robots)
        
        from nonebot.log import logger as nonebot_logger
        nonebot_logger.add(_loguru_sink, level="ERROR")

        bridge_handler = on_message(priority=10, block=False)

        def _resolve_bot_for_robot(robot_id: str) -> Bot | None:
            identity = _identity_by_robot_id.get(robot_id)
            if not identity:
                return None

            for bot in get_bots().values():
                try:
                    if resolve_bot_identity(bot) == identity:
                        return bot
                except Exception:
                    continue
            return None

        @bridge_handler.handle()
        async def handle_robot_message(bot: Bot, event: Event) -> None:
            loaded_robot_ids = list(_identity_by_robot_id.keys())
            logger.info(
                "[Bridge] Received platform event: bot=%s event=%s",
                getattr(bot, "self_id", None),
                event.__class__.__name__,
            )
            platform_id = resolve_platform_from_bot(bot)
            if not platform_id:
                record_loaded_robot_event(
                    loaded_robot_ids,
                    direction="platform_to_bridge",
                    event="event_ignored",
                    status="error",
                    message="Unsupported bot adapter",
                    payload={"bot_class": bot.__class__.__module__},
                )
                return

            try:
                bot_identity = resolve_bot_identity(bot)
            except Exception:
                record_loaded_robot_event(
                    loaded_robot_ids,
                    direction="platform_to_bridge",
                    event="event_ignored",
                    status="error",
                    message="Failed to resolve bot identity",
                    payload={"platform": platform_id},
                )
                logger.exception("[Bridge] Failed to resolve bot identity")
                return

            robot_id = _robot_id_by_identity.get(bot_identity)
            if not robot_id:
                record_loaded_robot_event(
                    loaded_robot_ids,
                    direction="platform_to_bridge",
                    event="event_ignored",
                    status="error",
                    message=f"No TermMan robot is mapped to identity {bot_identity}",
                    payload={
                        "platform": platform_id,
                        "bot_identity": bot_identity,
                        "known_identities": list(_robot_id_by_identity.keys()),
                    },
                )
                logger.warning(
                    "[Bridge] No TermMan robot is mapped to identity %s",
                    bot_identity,
                )
                return

            _seen_connected_robot_ids.add(robot_id)
            inbound = build_inbound_message(platform_id, bot, event)
            if inbound is None:
                record_robot_event(
                    robot_id,
                    direction="platform_to_bridge",
                    event="event_ignored",
                    status="error",
                    message="Inbound message is empty or unsupported",
                    payload={
                        "event_type": event.__class__.__name__,
                        "event": str(event),
                    },
                )
                return
            record_robot_event(
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
                record_robot_event(
                    robot_id,
                    direction="bridge_to_backend",
                    event="dispatch_failed",
                    status="error",
                    message=str(exc),
                )
                logger.exception("[Bridge] Failed to dispatch message for robot %s", robot_id)
                try:
                    await send_text_with_rate_limit(
                        bot,
                        inbound.reply_target,
                        f"Robot bridge failed: {exc}",
                        robot_id=robot_id,
                    )
                except Exception:
                    logger.exception(
                        "[Bridge] Failed to send bridge error back to platform for robot %s",
                        robot_id,
                    )
                return

            if dispatch.ignored:
                return

            for chunk in dispatch.reply_chunks:
                record_robot_event(
                    robot_id,
                    direction="bridge_to_platform",
                    event="platform_send",
                    message=chunk,
                    payload={
                        "target_type": inbound.reply_target.target_type,
                        "target_id": inbound.reply_target.target_id,
                    },
                )
                await send_text_with_rate_limit(
                    bot,
                    inbound.reply_target,
                    chunk,
                    robot_id=robot_id,
                )

        nonebot_app = get_asgi()

        _bridge_router = APIRouter(prefix="/robot-bridge", tags=["robot-bridge"])
        
        from nonebot import get_bots
        
        def _get_robot_id_for_adapter(adapter_name: str) -> str | None:
            adapter_lower = adapter_name.lower()
            for robot_id, identity in _identity_by_robot_id.items():
                if identity.startswith(adapter_lower):
                    return robot_id
            return None
        
        @_bridge_router.on_event("startup")
        async def startup_nonebot():
            global _connection_errors
            logger.info("[Bridge] Starting NoneBot adapters...")
            for adapter in driver._adapters.values():
                adapter_name = str(adapter.get_name())
                try:
                    await adapter.startup()
                    logger.info(f"[Bridge] Adapter {adapter_name} started")
                    robot_id = _get_robot_id_for_adapter(adapter_name)
                    if robot_id and robot_id in _connection_errors:
                        del _connection_errors[robot_id]
                except Exception as e:
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    logger.error(f"[Bridge] Failed to start adapter {adapter_name}: {error_msg}")
                    robot_id = _get_robot_id_for_adapter(adapter_name)
                    if robot_id:
                        _save_connection_error(robot_id, error_msg)
        
        from nonebot.internal.adapter.adapter import Adapter
        
        for adapter in driver._adapters.values():
            if hasattr(adapter, "run_bot_websocket"):
                original_run_bot_websocket = adapter.run_bot_websocket
                adapter_name = str(adapter.get_name())
                robot_id = _get_robot_id_for_adapter(adapter_name)
                if robot_id:
                    def make_wrapper(_original, _robot_id, _adapter_name):
                        async def wrapped_run_bot_websocket(bot, *args, **kwargs):
                            global _connection_errors
                            try:
                                result = await _original(bot, *args, **kwargs)
                                return result
                            except Exception as e:
                                error_msg = f"{type(e).__name__}: {str(e)}"
                                logger.error(f"[Bridge] WebSocket connection failed for {_adapter_name}: {error_msg}")
                                _save_connection_error(_robot_id, error_msg)
                                raise
                        return wrapped_run_bot_websocket
                    adapter.run_bot_websocket = make_wrapper(original_run_bot_websocket, robot_id, adapter_name)
                    logger.info(f"[Bridge] Wrapped run_bot_websocket for adapter {adapter_name}")
        
        @_bridge_router.on_event("shutdown")
        async def shutdown_nonebot():
            logger.info("[Bridge] Stopping NoneBot adapters...")
            for bot in driver._adapters.values():
                try:
                    await bot.shutdown()
                except Exception as e:
                    logger.error(f"[Bridge] Failed to stop adapter: {e}")

        @_bridge_router.post("/internal/send")
        async def internal_send(
            body: RobotBridgeSendRequest,
            x_termman_bridge_token: str | None = Header(default=None),
        ) -> dict[str, Any]:
            _assert_bridge_permission(x_termman_bridge_token)

            robot_id = str(body.robot_id)
            bot = _resolve_bot_for_robot(robot_id)
            if bot is None:
                raise HTTPException(status_code=404, detail="Robot is not loaded in bridge")

            record_robot_event(
                robot_id,
                direction="bridge_to_platform",
                event="internal_send",
                message=body.text,
                payload={
                    "target_type": body.target.target_type,
                    "target_id": body.target.target_id,
                },
            )
            await send_text_with_rate_limit(
                bot,
                body.target,
                body.text,
                robot_id=robot_id,
            )
            return {"success": True}

        @_bridge_router.post("/internal/reload", response_model=RobotBridgeReloadResponse)
        async def internal_reload(
            x_termman_bridge_token: str | None = Header(default=None),
        ) -> RobotBridgeReloadResponse:
            _assert_bridge_permission(x_termman_bridge_token)

            def _restart() -> None:
                time.sleep(0.2)
                os._exit(0)

            threading.Thread(target=_restart, daemon=True).start()
            return RobotBridgeReloadResponse(success=True, detail="Bridge restart scheduled")

        @_bridge_router.get("/internal/health")
        async def internal_health() -> dict[str, Any]:
            checked_at = datetime.now(timezone.utc).isoformat()
            _load_connection_errors()
            connected_bot_count = len(get_bots())
            connected_identities = [
                identity
                for robot_id, identity in _identity_by_robot_id.items()
                if robot_id in _seen_connected_robot_ids
                or connected_bot_count > 0
            ]

            robot_status: dict[str, dict[str, Any]] = {}
            for robot_id, identity in _identity_by_robot_id.items():
                robot_status[robot_id] = {
                    "identity": identity,
                    "connected": identity in connected_identities,
                    "error": None
                    if identity in connected_identities
                    else (_connection_errors.get(robot_id) or {}).get("message"),
                    "last_error": _connection_errors.get(robot_id),
                }

            backend_status: dict[str, Any] = {"reachable": False}
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{settings.ROBOT_BACKEND_URL.rstrip('/')}{settings.API_V1_STR}/utils/health-check/",
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
                "loaded_robot_count": len(_identity_by_robot_id),
                "connected_bot_count": connected_bot_count,
                "platforms": sorted(
                    {
                        normalize_robot_platform_id(robot.platform or robot.protocol)
                        for robot in _loaded_robots
                    }
                ),
                "connected_identities": connected_identities,
                "robots": robot_status,
                "backend": backend_status,
                "connection_errors": _connection_errors,
            }

        logger.info(
            "[Bridge] Embedded bridge initialized with %d robot(s), platforms: %s",
            len(_loaded_robots),
            sorted({normalize_robot_platform_id(r.platform or r.protocol) for r in _loaded_robots}),
        )
        return _bridge_router

    except Exception as e:
        logger.exception("[Bridge] Failed to initialize embedded bridge: %s", e)
        return None


def resolve_robot_identity(platform_id: str, robot) -> str:
    from app.plugins.robot.platforms import resolve_robot_identity as _resolve
    return _resolve(platform_id, robot)
