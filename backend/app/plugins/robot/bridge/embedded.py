from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
import uvicorn
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Header, HTTPException

from app.core.config import settings
from app.plugins.robot.contracts import (
    RobotBridgeReloadResponse,
    RobotBridgeSendRequest,
    RobotDispatchResponse,
    RobotInboundMessage,
)
from app.plugins.robot.debug_log import (
    preview_text,
    record_loaded_robot_event,
    record_robot_event,
)
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
_last_platform_event_at_by_robot_id: dict[str, str] = {}
_last_message_event_at_by_robot_id: dict[str, str] = {}
_initialized = False
_connection_errors: dict[str, dict[str, str]] = {}
_error_file_path: str = "/tmp/robot_bridge_errors.json"
_identity_file_path: str = "/tmp/robot_bridge_identities.json"
_cooldown_file_path: str = "/tmp/robot_bridge_cooldowns.json"
_singleton_lock_path: str = str(Path(tempfile.gettempdir()) / "termman_robot_bridge.lock")
_owner_info_path: str = str(Path(tempfile.gettempdir()) / "termman_robot_bridge_owner.json")
_singleton_lock_file: Any | None = None
_singleton_lock_owner = False
_singleton_lock_guard = threading.Lock()
_ipc_server: uvicorn.Server | None = None
_ipc_thread: threading.Thread | None = None
_ipc_base_url: str | None = None
QQ_GATEWAY_RATE_LIMIT_COOLDOWN_SECONDS = 600


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


def _is_rate_limit_error(error: str) -> bool:
    return "100017" in error or "频率限制" in error or "rate limit" in error.lower()


def _is_empty_resumed_payload(payload: Any) -> bool:
    return (
        str(getattr(payload, "type", "") or "").upper() == "RESUMED"
        and not isinstance(getattr(payload, "data", None), dict)
    )


def _acquire_singleton_lock() -> bool:
    global _singleton_lock_file, _singleton_lock_owner
    with _singleton_lock_guard:
        if _singleton_lock_owner:
            return True

        Path(_singleton_lock_path).parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(_singleton_lock_path, "a+")
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
        _singleton_lock_file = lock_file
        _singleton_lock_owner = True
        return True


def _release_singleton_lock() -> None:
    global _singleton_lock_file, _singleton_lock_owner
    with _singleton_lock_guard:
        lock_file = _singleton_lock_file
        if lock_file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            lock_file.close()
        except OSError:
            pass
        _singleton_lock_file = None
        _singleton_lock_owner = False


def _write_owner_info(base_url: str) -> None:
    try:
        import json

        with open(_owner_info_path, "w") as f:
            json.dump(
                {
                    "pid": os.getpid(),
                    "base_url": base_url,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                f,
            )
    except Exception:
        logger.exception("[Bridge] Failed to write IPC owner info")


def _read_owner_info() -> dict[str, Any] | None:
    try:
        import json

        with open(_owner_info_path, "r") as f:
            raw = json.load(f)
        if isinstance(raw, dict) and raw.get("base_url"):
            return raw
    except Exception:
        return None
    return None


def _remove_owner_info() -> None:
    try:
        os.remove(_owner_info_path)
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("[Bridge] Failed to remove IPC owner info")


async def _forward_to_owner(
    path: str,
    *,
    body: Any | None = None,
    timeout: float = 10.0,
    method: str = "POST",
) -> dict[str, Any]:
    owner_info = _read_owner_info()
    if not owner_info:
        raise HTTPException(status_code=503, detail="Robot bridge owner is not available")

    base_url = str(owner_info["base_url"]).rstrip("/")
    shared_secret = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY
    headers = {"X-TermMan-Bridge-Token": shared_secret}
    if body is not None:
        headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        if body is None:
            if method.upper() == "GET":
                response = await client.get(f"{base_url}{path}", headers=headers)
            else:
                response = await client.post(f"{base_url}{path}", headers=headers)
        else:
            response = await client.post(
                f"{base_url}{path}",
                headers=headers,
                content=body.model_dump_json() if hasattr(body, "model_dump_json") else None,
                json=None if hasattr(body, "model_dump_json") else body,
            )
        response.raise_for_status()
        return response.json()


def _start_ipc_server(send_handler, health_handler, reload_handler) -> str:
    global _ipc_base_url, _ipc_server, _ipc_thread
    if _ipc_base_url:
        return _ipc_base_url

    app = FastAPI()

    @app.post("/internal/send")
    async def ipc_send(
        body: RobotBridgeSendRequest,
        x_termman_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _assert_bridge_permission(x_termman_bridge_token)
        return await send_handler(body)

    @app.get("/internal/health")
    async def ipc_health(
        x_termman_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _assert_bridge_permission(x_termman_bridge_token)
        return await health_handler()

    @app.post("/internal/reload")
    async def ipc_reload(
        x_termman_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _assert_bridge_permission(x_termman_bridge_token)
        return await reload_handler()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    started = threading.Event()
    failed: list[BaseException] = []

    def run_server() -> None:
        try:
            server.config.load()
            server.lifespan = server.config.lifespan_class(server.config)
            import asyncio

            async def serve() -> None:
                await server.startup()
                started.set()
                if server.should_exit:
                    return
                await server.main_loop()
                await server.shutdown()

            asyncio.run(serve())
        except BaseException as exc:
            failed.append(exc)
            started.set()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    if not started.wait(timeout=5.0):
        raise RuntimeError("Timed out starting robot bridge IPC server")
    if failed:
        raise RuntimeError(f"Failed to start robot bridge IPC server: {failed[0]}")
    if not server.servers:
        raise RuntimeError("Robot bridge IPC server did not expose a socket")

    sockname = server.servers[0].sockets[0].getsockname()
    base_url = f"http://127.0.0.1:{sockname[1]}"
    _ipc_server = server
    _ipc_thread = thread
    _ipc_base_url = base_url
    _write_owner_info(base_url)
    logger.info("[Bridge] IPC owner server started at %s", base_url)
    return base_url


def _stop_ipc_server() -> None:
    global _ipc_base_url, _ipc_server, _ipc_thread
    if _ipc_server is not None:
        _ipc_server.should_exit = True
    if _ipc_thread is not None and _ipc_thread.is_alive():
        _ipc_thread.join(timeout=3.0)
    _ipc_server = None
    _ipc_thread = None
    _ipc_base_url = None
    _remove_owner_info()


def _load_cooldowns() -> dict[str, float]:
    try:
        import json
        with open(_cooldown_file_path, "r") as f:
            raw = json.load(f)
        return {str(key): float(value) for key, value in raw.items()}
    except Exception:
        return {}


def _save_cooldowns(cooldowns: dict[str, float]) -> None:
    try:
        import json
        with open(_cooldown_file_path, "w") as f:
            json.dump(cooldowns, f)
    except Exception:
        pass


def _set_gateway_cooldown(robot_id: str) -> float:
    until = time.time() + QQ_GATEWAY_RATE_LIMIT_COOLDOWN_SECONDS
    cooldowns = _load_cooldowns()
    cooldowns[robot_id] = until
    _save_cooldowns(cooldowns)
    return until


def _get_gateway_cooldown_remaining(robot_id: str) -> int:
    cooldowns = _load_cooldowns()
    remaining = int(cooldowns.get(robot_id, 0) - time.time())
    if remaining <= 0 and robot_id in cooldowns:
        cooldowns.pop(robot_id, None)
        _save_cooldowns(cooldowns)
    return max(0, remaining)


def _serialize_bot_snapshot(bot: Any) -> dict[str, Any]:
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


def _serialize_event_payload(event: Any) -> dict[str, Any]:
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


def _build_ready_event_payload(
    platform_id: str,
    bot_identity: str,
    event: Any,
) -> tuple[str, dict[str, Any]]:
    event_payload = _serialize_event_payload(event)
    user = event_payload.get("user") if isinstance(event_payload.get("user"), dict) else {}
    payload = {
        "platform": platform_id,
        "bot_identity": bot_identity,
        "event_type": event.__class__.__name__,
        "session_id": event_payload.get("session_id"),
        "version": event_payload.get("version"),
        "shard": event_payload.get("shard"),
        "user_id": user.get("id"),
        "username": user.get("username"),
        "bot": user.get("bot"),
    }
    message = (
        f"QQ bot ready: {payload.get('username') or payload.get('user_id') or bot_identity}"
        f" session={payload.get('session_id') or '-'}"
    )
    return message, {key: value for key, value in payload.items() if value is not None}


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
    _last_platform_event_at_by_robot_id[robot_id] = timestamp
    if event == "platform_message":
        _last_message_event_at_by_robot_id[robot_id] = timestamp
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


def get_bridge_router() -> APIRouter | None:
    global _bridge_router
    return _bridge_router


def get_loaded_robots() -> tuple[list, dict[str, str], dict[str, str]]:
    return _loaded_robots, _robot_id_by_identity, _identity_by_robot_id


def _build_idle_bridge_router(reason: str) -> APIRouter:
    router = APIRouter(prefix="/robot-bridge", tags=["robot-bridge"])

    @router.post("/internal/send")
    async def internal_send(
        body: RobotBridgeSendRequest,
        x_termman_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _assert_bridge_permission(x_termman_bridge_token)
        return await _forward_to_owner("/internal/send", body=body)

    @router.post("/internal/reload", response_model=RobotBridgeReloadResponse)
    async def internal_reload(
        x_termman_bridge_token: str | None = Header(default=None),
    ) -> RobotBridgeReloadResponse:
        _assert_bridge_permission(x_termman_bridge_token)
        result = await _forward_to_owner("/internal/reload")
        return RobotBridgeReloadResponse.model_validate(result)

    @router.get("/internal/health")
    async def internal_health(
        x_termman_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _assert_bridge_permission(x_termman_bridge_token)
        try:
            owner_health = await _forward_to_owner("/internal/health", timeout=5.0, method="GET")
            owner_health["proxy_worker"] = {
                "pid": os.getpid(),
                "status": "forwarded_to_owner",
                "reason": reason,
            }
            return owner_health
        except Exception as exc:
            checked_at = datetime.now(timezone.utc).isoformat()
            return {
                "checked_at": checked_at,
                "live": True,
                "status": "idle",
                "reason": reason,
                "owner_error": str(exc),
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

    if not _acquire_singleton_lock():
        logger.info(
            "[Bridge] Another backend process already owns the robot bridge lock; "
            "skip initializing NoneBot in this worker"
        )
        _bridge_router = _build_idle_bridge_router("robot_bridge_lock_owned_by_another_process")
        return _bridge_router

    try:
        import nonebot
    except ImportError:
        logger.info("[Bridge] nonebot not installed, skip bridge initialization")
        _bridge_router = _build_idle_bridge_router("nonebot_not_installed")
        return _bridge_router

    try:
        from nonebot import get_asgi, get_bots, on, on_message
        from nonebot.adapters import Bot, Event
        from sqlmodel import Session, select

        globals()["Bot"] = Bot
        globals()["Event"] = Event

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

        for adapter in driver._adapters.values():
            if str(adapter.get_name()).lower() == "qq" and hasattr(adapter, "dispatch_event"):
                original_dispatch_event = adapter.dispatch_event

                def make_dispatch_wrapper(_original):
                    def wrapped_dispatch_event(bot, payload):
                        if _is_empty_resumed_payload(payload):
                            logger.info("[Bridge] Ignored empty QQ RESUMED payload")
                            return None
                        return _original(bot, payload)

                    return wrapped_dispatch_event

                adapter.dispatch_event = make_dispatch_wrapper(original_dispatch_event)
                logger.info("[Bridge] Patched QQ empty RESUMED payload handling")

        event_probe = on(priority=1, block=False)
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

        @event_probe.handle()
        async def probe_robot_event(bot: Bot, event: Event) -> None:
            loaded_robot_ids = list(_identity_by_robot_id.keys())
            platform_id = resolve_platform_from_bot(bot)
            if not platform_id:
                return
            try:
                bot_identity = resolve_bot_identity(bot)
            except Exception:
                return
            robot_id = _robot_id_by_identity.get(bot_identity)
            if robot_id:
                _seen_connected_robot_ids.add(robot_id)
                event_name = event.__class__.__name__
                if "ready" in event_name.lower():
                    message, payload = _build_ready_event_payload(
                        platform_id,
                        bot_identity,
                        event,
                    )
                    _record_bridge_event(
                        robot_id,
                        direction="platform_to_bridge",
                        event="bot_ready",
                        message=message,
                        payload=payload,
                    )
                    return
                _record_bridge_event(
                    robot_id,
                    direction="platform_to_bridge",
                    event="platform_event",
                    message=event_name,
                    payload={
                        "platform": platform_id,
                        "bot_identity": bot_identity,
                        "event_type": event_name,
                        "event": str(event),
                    },
                )
            elif loaded_robot_ids:
                record_loaded_robot_event(
                    loaded_robot_ids,
                    direction="platform_to_bridge",
                    event="platform_event_unmapped",
                    status="error",
                    message=event.__class__.__name__,
                    payload={
                        "platform": platform_id,
                        "bot_identity": bot_identity,
                    },
                )

        @bridge_handler.handle()
        async def handle_robot_message(bot: Bot, event: Event) -> None:
            loaded_robot_ids = list(_identity_by_robot_id.keys())
            logger.info(
                "[Bridge] Received platform event: bot=%s event=%s raw=%s",
                getattr(bot, "self_id", None),
                event.__class__.__name__,
                preview_text(event),
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
            logger.info(
                "[Bridge] Platform message robot=%s sender=%s target=%s text=%s",
                robot_id,
                inbound.sender_key,
                inbound.reply_target.target_id,
                preview_text(inbound.text),
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
                logger.info(
                    "[Bridge] Sending platform reply robot=%s target=%s text=%s",
                    robot_id,
                    inbound.reply_target.target_id,
                    preview_text(chunk),
                )
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
            _start_ipc_server(_send_from_owner, _health_from_owner, _reload_owner)
        
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
                            remaining = _get_gateway_cooldown_remaining(_robot_id)
                            if remaining > 0:
                                error_msg = (
                                    "QQ gateway info is rate limited; "
                                    f"websocket start is cooling down for {remaining}s"
                                )
                                logger.warning("[Bridge] %s", error_msg)
                                _save_connection_error(_robot_id, error_msg)
                                return None
                            try:
                                result = await _original(bot, *args, **kwargs)
                                return result
                            except Exception as e:
                                error_msg = f"{type(e).__name__}: {str(e)}"
                                logger.error(f"[Bridge] WebSocket connection failed for {_adapter_name}: {error_msg}")
                                _save_connection_error(_robot_id, error_msg)
                                if _is_rate_limit_error(error_msg):
                                    until = _set_gateway_cooldown(_robot_id)
                                    logger.warning(
                                        "[Bridge] QQ gateway rate limited; cooldown until %s",
                                        datetime.fromtimestamp(until, timezone.utc).isoformat(),
                                    )
                                    return None
                                raise
                        return wrapped_run_bot_websocket
                    adapter.run_bot_websocket = make_wrapper(original_run_bot_websocket, robot_id, adapter_name)
                    logger.info(f"[Bridge] Wrapped run_bot_websocket for adapter {adapter_name}")
        
        @_bridge_router.on_event("shutdown")
        async def shutdown_nonebot():
            logger.info("[Bridge] Stopping NoneBot adapters...")
            _stop_ipc_server()
            for bot in driver._adapters.values():
                try:
                    await bot.shutdown()
                except Exception as e:
                    logger.error(f"[Bridge] Failed to stop adapter: {e}")
            _release_singleton_lock()

        async def _send_from_owner(body: RobotBridgeSendRequest) -> dict[str, Any]:
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

        @_bridge_router.post("/internal/send")
        async def internal_send(
            body: RobotBridgeSendRequest,
            x_termman_bridge_token: str | None = Header(default=None),
        ) -> dict[str, Any]:
            _assert_bridge_permission(x_termman_bridge_token)
            try:
                return await _send_from_owner(body)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                return await _forward_to_owner("/internal/send", body=body)

        async def _health_from_owner() -> dict[str, Any]:
            checked_at = datetime.now(timezone.utc).isoformat()
            _load_connection_errors()
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
            connected_identities = [
                identity
                for robot_id, identity in _identity_by_robot_id.items()
                if robot_id in _seen_connected_robot_ids
                or connected_bot_count > 0
            ]

            robot_status: dict[str, dict[str, Any]] = {}
            for robot_id, identity in _identity_by_robot_id.items():
                cooldown_remaining = _get_gateway_cooldown_remaining(robot_id)
                robot_status[robot_id] = {
                    "identity": identity,
                    "connected": identity in connected_identities,
                    "bot": bot_snapshot_by_identity.get(identity),
                    "last_platform_event_at": _last_platform_event_at_by_robot_id.get(robot_id),
                    "last_message_event_at": _last_message_event_at_by_robot_id.get(robot_id),
                    "error": (
                        f"QQ gateway rate limited; retry after {cooldown_remaining}s"
                        if cooldown_remaining > 0
                        else None
                        if identity in connected_identities
                        else (_connection_errors.get(robot_id) or {}).get("message")
                    ),
                    "last_error": _connection_errors.get(robot_id),
                    "cooldown_remaining_seconds": cooldown_remaining,
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
                "bots": bot_snapshots,
                "robots": robot_status,
                "backend": backend_status,
                "connection_errors": _connection_errors,
                "ipc_owner": {
                    "pid": os.getpid(),
                    "base_url": _ipc_base_url,
                },
            }

        async def _reload_owner() -> dict[str, Any]:
            errors: list[str] = []
            for adapter in driver._adapters.values():
                adapter_name = str(adapter.get_name())
                try:
                    logger.info("[Bridge] Soft-reloading adapter %s: shutdown", adapter_name)
                    await adapter.shutdown()
                except Exception as exc:
                    error_msg = f"{adapter_name} shutdown failed: {type(exc).__name__}: {exc}"
                    logger.warning("[Bridge] %s", error_msg)
                    errors.append(error_msg)

            for adapter in driver._adapters.values():
                adapter_name = str(adapter.get_name())
                try:
                    logger.info("[Bridge] Soft-reloading adapter %s: startup", adapter_name)
                    await adapter.startup()
                except Exception as exc:
                    error_msg = f"{adapter_name} startup failed: {type(exc).__name__}: {exc}"
                    logger.error("[Bridge] %s", error_msg)
                    errors.append(error_msg)

            if errors:
                return {
                    "success": False,
                    "detail": "; ".join(errors),
                }
            return {
                "success": True,
                "detail": "Bridge adapters soft-reloaded without restarting worker",
            }

        @_bridge_router.post("/internal/reload", response_model=RobotBridgeReloadResponse)
        async def internal_reload(
            x_termman_bridge_token: str | None = Header(default=None),
        ) -> RobotBridgeReloadResponse:
            _assert_bridge_permission(x_termman_bridge_token)
            return RobotBridgeReloadResponse.model_validate(await _reload_owner())

        @_bridge_router.get("/internal/health")
        async def internal_health(
            x_termman_bridge_token: str | None = Header(default=None),
        ) -> dict[str, Any]:
            _assert_bridge_permission(x_termman_bridge_token)
            return await _health_from_owner()

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
