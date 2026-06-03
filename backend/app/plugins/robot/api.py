import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Item,
    Message,
    Robot,
    RobotCreate,
    RobotItem,
    RobotPublic,
    RobotsPublic,
    RobotUpdate,
)

from .api_support import (
    assert_bridge_permission,
    assert_item_permission,
    assert_robot_permission,
    clear_default_targets,
    current_robot_config,
    ensure_unique_binding_route_key,
    ensure_unique_robot_name,
    get_item_or_404,
    get_robot_or_404,
    normalize_binding_payload,
    normalize_robot_stack,
    serialize_binding,
    validate_binding_payload,
)
from .bridge_client import robot_bridge_client
from .contracts import RobotDispatchResponse, RobotInboundMessage
from .debug_log import get_robot_events, record_robot_event
from .platforms import (
    RobotPlatformPublic,
    get_robot_platform,
    get_robot_runtime_config,
    list_supported_robot_platforms,
    normalize_robot_config,
    normalize_robot_platform_id,
    resolve_robot_identity,
)
from .schemas import (
    RobotItemBindingCreate,
    RobotItemBindingPublic,
    RobotItemBindingUpdate,
)
from .service import robot_service

router = APIRouter(prefix="/robots", tags=["robots"])


def _event_seen(events: list[dict], names: set[str]) -> bool:
    return any(str(event.get("event") or "") in names for event in events)


@router.get("/platforms", response_model=list[RobotPlatformPublic])
def list_robot_platform_metadata() -> list[RobotPlatformPublic]:
    return list_supported_robot_platforms()


@router.get("/bridge/health")
def get_bridge_health(current_user: CurrentUser) -> dict:
    del current_user

    import httpx

    from app.core.config import settings

    try:
        response = httpx.get(
            f"{settings.ROBOT_BRIDGE_URL}/internal/health",
            headers={
                "X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET
                or settings.SECRET_KEY
            },
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e), "connected": False}


@router.get("/bridge/runtime-config")
def get_bridge_runtime_config(
    session: SessionDep,
    x_termman_bridge_token: str | None = Header(default=None),
) -> dict:
    assert_bridge_permission(x_termman_bridge_token)

    robots = session.exec(
        select(Robot).where(
            Robot.is_enabled == True,  # noqa: E712
            Robot.provider == "nonebot2",
        )
    ).all()

    loaded_robots: list[dict] = []
    robot_id_by_identity: dict[str, str] = {}
    identity_by_robot_id: dict[str, str] = {}
    errors: dict[str, str] = {}

    for robot in robots:
        robot_id = str(robot.id)
        platform_id = normalize_robot_platform_id(robot.platform or robot.protocol)
        try:
            runtime_config = get_robot_runtime_config(robot)
            identity = resolve_robot_identity(platform_id, robot)
        except Exception as exc:
            errors[robot_id] = str(exc)
            continue
        if identity in robot_id_by_identity:
            errors[robot_id] = f"Duplicate robot identity `{identity}`"
            continue

        loaded_robots.append(
            {
                "id": robot_id,
                "platform": platform_id,
                "protocol": platform_id,
                "provider": robot.provider,
                "name": robot.name,
                "runtime_config": runtime_config,
                "identity": identity,
            }
        )
        robot_id_by_identity[identity] = robot_id
        identity_by_robot_id[robot_id] = identity

    return {
        "robots": loaded_robots,
        "robot_id_by_identity": robot_id_by_identity,
        "identity_by_robot_id": identity_by_robot_id,
        "errors": errors,
    }


@router.get("/", response_model=RobotsPublic)
def read_robots(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
) -> RobotsPublic:
    if current_user.is_superuser:
        statement = (
            select(Robot)
            .order_by(col(Robot.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        robots = session.exec(statement).all()
    else:
        statement = (
            select(Robot)
            .where(Robot.owner_id == current_user.id)
            .order_by(col(Robot.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        robots = session.exec(statement).all()

    return RobotsPublic(data=robots, count=len(robots))


@router.get("/{id}", response_model=RobotPublic)
def read_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> RobotPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)
    return robot


@router.post("/", response_model=RobotPublic)
def create_robot(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    robot_in: RobotCreate,
) -> RobotPublic:
    ensure_unique_robot_name(session, current_user, robot_in.name)

    payload = robot_in.model_dump()
    _, update = normalize_robot_stack(
        str(payload.get("platform") or ""),
        payload.get("config"),
    )

    robot = Robot.model_validate(
        robot_in,
        update={
            "owner_id": current_user.id,
            **update,
        },
    )
    session.add(robot)
    session.commit()
    session.refresh(robot)
    robot_bridge_client.notify_reload()
    return robot


@router.put("/{id}", response_model=RobotPublic)
def update_robot(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    robot_in: RobotUpdate,
) -> RobotPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    if robot_in.name and robot_in.name != robot.name:
        ensure_unique_robot_name(
            session,
            current_user,
            robot_in.name,
            exclude_robot_id=robot.id,
        )

    update_dict = robot_in.model_dump(exclude_unset=True)
    merged_platform = normalize_robot_platform_id(
        str(update_dict.get("platform") or robot.platform or robot.protocol or "")
    )
    if "config" in update_dict:
        incoming_config = update_dict.get("config")
        if isinstance(incoming_config, dict):
            existing_config = current_robot_config(robot)
            incoming_credentials = incoming_config.get("credentials")
            if isinstance(incoming_credentials, dict):
                merged_credentials = dict(existing_config.get("credentials") or {})
                platform = get_robot_platform(merged_platform)
                secret_keys = {field.key for field in platform.fields if field.secret}
                for key, value in incoming_credentials.items():
                    if value not in (None, "") or key not in secret_keys:
                        merged_credentials[str(key)] = value
                incoming_config = {
                    **incoming_config,
                    "credentials": merged_credentials,
                }
        merged_config = normalize_robot_config(
            merged_platform,
            incoming_config,
        )
    else:
        merged_config = current_robot_config(robot)
    _, normalized_update = normalize_robot_stack(merged_platform, merged_config)

    if "name" in update_dict and update_dict["name"] is not None:
        normalized_update["name"] = str(update_dict["name"]).strip()
    if "is_enabled" in update_dict:
        normalized_update["is_enabled"] = update_dict["is_enabled"]

    robot.sqlmodel_update(normalized_update)
    session.add(robot)
    session.commit()
    session.refresh(robot)
    robot_bridge_client.notify_reload()
    return robot


@router.delete("/{id}")
def delete_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> Message:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    session.delete(robot)
    session.commit()
    robot_bridge_client.notify_reload()
    return Message(message="Robot deleted successfully")


@router.get("/{id}/items", response_model=list[RobotItemBindingPublic])
def list_robot_item_bindings(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> list[RobotItemBindingPublic]:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    bindings = session.exec(select(RobotItem).where(RobotItem.robot_id == id)).all()
    return [serialize_binding(session, binding) for binding in bindings]


@router.post("/{id}/items", response_model=RobotItemBindingPublic)
def bind_item_to_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    body: RobotItemBindingCreate,
) -> RobotItemBindingPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    item = get_item_or_404(session, body.item_id)
    assert_item_permission(item, current_user)

    existing = session.exec(
        select(RobotItem).where(
            RobotItem.robot_id == id,
            RobotItem.item_id == body.item_id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=400, detail="Item is already bound to this robot"
        )

    payload = normalize_binding_payload(body)
    validate_binding_payload(payload)
    route_key = ensure_unique_binding_route_key(
        session,
        id,
        item,
        chat_alias=payload.get("chat_alias"),
    )

    binding = RobotItem(
        robot_id=id,
        item_id=body.item_id,
        allow_chat=payload.get("allow_chat", True),
        receive_filtered_output=payload.get("receive_filtered_output", False),
        chat_alias=payload.get("chat_alias"),
        is_default_target=payload.get("is_default_target", False),
    )

    if binding.is_default_target:
        clear_default_targets(session, id)

    session.add(binding)
    session.commit()
    session.refresh(binding)

    response = serialize_binding(session, binding)
    response.route_key = route_key
    return response


@router.put("/{id}/items/{item_id}", response_model=RobotItemBindingPublic)
def update_robot_item_binding(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_id: uuid.UUID,
    body: RobotItemBindingUpdate,
) -> RobotItemBindingPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    binding = session.exec(
        select(RobotItem).where(
            RobotItem.robot_id == id,
            RobotItem.item_id == item_id,
        )
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Robot item binding not found")

    item = get_item_or_404(session, item_id)
    assert_item_permission(item, current_user)

    payload = normalize_binding_payload(body)
    merged_payload = {
        "allow_chat": binding.allow_chat,
        "receive_filtered_output": binding.receive_filtered_output,
        "chat_alias": binding.chat_alias,
        "is_default_target": binding.is_default_target,
    }
    merged_payload.update(payload)
    validate_binding_payload(merged_payload)

    if "chat_alias" in payload:
        ensure_unique_binding_route_key(
            session,
            id,
            item,
            chat_alias=merged_payload.get("chat_alias"),
            exclude_item_id=item_id,
        )

    if merged_payload.get("is_default_target"):
        clear_default_targets(session, id, exclude_item_id=item_id)

    binding.allow_chat = merged_payload["allow_chat"]
    binding.receive_filtered_output = merged_payload["receive_filtered_output"]
    binding.chat_alias = merged_payload["chat_alias"]
    binding.is_default_target = merged_payload["is_default_target"]

    if not binding.allow_chat:
        binding.is_default_target = False

    session.add(binding)
    session.commit()
    session.refresh(binding)
    return serialize_binding(session, binding)


@router.delete("/{id}/items/{item_id}")
def unbind_item_from_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_id: uuid.UUID,
) -> Message:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    binding = session.exec(
        select(RobotItem).where(
            RobotItem.robot_id == id,
            RobotItem.item_id == item_id,
        )
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Robot item binding not found")

    session.delete(binding)
    session.commit()
    return Message(message="Robot item binding deleted successfully")


@router.post("/{id}/dispatch", response_model=RobotDispatchResponse)
async def dispatch_robot_message(
    session: SessionDep,
    id: uuid.UUID,
    body: RobotInboundMessage,
    x_termman_bridge_token: str | None = Header(default=None),
) -> RobotDispatchResponse:
    assert_bridge_permission(x_termman_bridge_token)
    robot = get_robot_or_404(session, id)
    return await robot_service.handle_inbound_message(session, robot, body)


@router.post("/{id}/debug-events")
def ingest_robot_debug_event(
    session: SessionDep,
    id: uuid.UUID,
    body: dict,
    x_termman_bridge_token: str | None = Header(default=None),
) -> dict:
    assert_bridge_permission(x_termman_bridge_token)
    get_robot_or_404(session, id)
    record_robot_event(
        str(id),
        direction=str(body.get("direction") or "bridge"),
        event=str(body.get("event") or "debug_event"),
        status=str(body.get("status") or "ok"),
        message=body.get("message"),
        payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
    )
    return {"success": True}


@router.get("/{id}/connection")
def get_robot_connection_status(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> dict:
    import httpx

    from app.core.config import settings

    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    if not robot.is_enabled:
        return {"robot_id": str(id), "connected": False, "reason": "robot_disabled"}

    try:
        response = httpx.get(
            f"{settings.ROBOT_BRIDGE_URL}/internal/health",
            headers={
                "X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET
                or settings.SECRET_KEY
            },
            timeout=5.0,
        )
        response.raise_for_status()
        health_data = response.json()

        robots_status = health_data.get("robots", {})
        robot_status = robots_status.get(str(id), {})

        return {
            "robot_id": str(id),
            "identity": robot_status.get("identity"),
            "connected": robot_status.get("connected", False),
            "platform": robot.platform,
        }
    except Exception as e:
        return {"robot_id": str(id), "connected": False, "error": str(e)}


@router.get("/{id}/diagnose")
def diagnose_robot_chain(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> dict:
    import httpx

    from app.core.config import settings
    from app.services import backend_conn_pool

    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)
    platform_id = normalize_robot_platform_id(robot.platform or robot.protocol)
    uses_napcat_socket = platform_id == "onebot_v11"

    result: dict = {
        "robot_id": str(id),
        "robot_name": robot.name,
        "robot_enabled": robot.is_enabled,
        "platform": robot.platform,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "chain": {},
    }

    result["chain"]["robot_config"] = {
        "status": "ok" if robot.is_enabled else "disabled",
        "app_id": robot.app_id,
        "provider": robot.provider,
    }

    recent_events = get_robot_events(str(id), limit=200)
    bridge_status: dict = {"status": "unknown", "connected": False}
    socket_status: dict = {
        "status": "unknown" if uses_napcat_socket else "not_applicable",
        "connected": not uses_napcat_socket,
    }
    try:
        response = httpx.get(
            f"{settings.ROBOT_BRIDGE_URL}/internal/health",
            headers={
                "X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET
                or settings.SECRET_KEY
            },
            timeout=5.0,
        )
        response.raise_for_status()
        health_data = response.json()

        robots_status = health_data.get("robots", {})
        robot_status = robots_status.get(str(id), {})
        backend_status = health_data.get("backend", {})
        connection_errors = health_data.get("connection_errors", {})
        raw_connection_error = connection_errors.get(str(id))
        historical_error = (
            raw_connection_error.get("message")
            if isinstance(raw_connection_error, dict)
            else raw_connection_error
        )
        historical_error_at = (
            raw_connection_error.get("timestamp")
            if isinstance(raw_connection_error, dict)
            else None
        )
        current_error = robot_status.get("error")
        connected = robot_status.get("connected", False)
        onebot_socket = (
            robot_status.get("onebot_socket")
            if isinstance(robot_status.get("onebot_socket"), dict)
            else {}
        )

        bridge_status = {
            "status": "ok",
            "connected": connected,
            "identity": robot_status.get("identity"),
            "backend_reachable": backend_status.get("reachable", False),
            "error": None if connected else current_error or historical_error,
            "stale_error": historical_error if connected else None,
            "stale_error_at": historical_error_at if connected else None,
            "bridge_checked_at": health_data.get("checked_at"),
            "live": bool(health_data.get("live", False)),
        }
        if uses_napcat_socket:
            socket_connected = bool(onebot_socket.get("connected"))
            socket_status = {
                "status": "ok" if socket_connected else "waiting",
                "connected": socket_connected,
                "last_event": onebot_socket.get("event"),
                "last_event_at": onebot_socket.get("last_event_at"),
                "socket_path": onebot_socket.get("socket_path"),
                "client": onebot_socket.get("client"),
                "self_id": onebot_socket.get("self_id"),
                "last_message_seen": _event_seen(
                    recent_events,
                    {"platform_message", "inbound_message"},
                ),
                "last_socket_receive_seen": _event_seen(
                    recent_events,
                    {"websocket_receive"},
                ),
            }
    except Exception as e:
        bridge_status = {"status": "error", "error": str(e), "connected": False}
        socket_status = {
            "status": "error" if uses_napcat_socket else "not_applicable",
            "error": str(e),
            "connected": False if uses_napcat_socket else True,
        }

    result["chain"]["qq_to_bridge"] = bridge_status
    result["chain"]["napcat_socket"] = socket_status

    bindings = session.exec(select(RobotItem).where(RobotItem.robot_id == id)).all()
    items_status: list[dict] = []

    for binding in bindings:
        item = session.get(Item, binding.item_id)
        if not item:
            continue

        item_status: dict = {
            "item_id": str(item.id),
            "item_title": item.title,
            "allow_chat": binding.allow_chat,
            "receive_filtered_output": binding.receive_filtered_output,
            "is_default_target": binding.is_default_target,
            "route_key": robot_service.build_route_key(item, binding),
        }

        daemon_status: dict = {"status": "unknown", "online": False}
        if item.api_key:
            daemon_state = backend_conn_pool.get_daemon_main_conn_state(item.api_key)
            if daemon_state and daemon_state.is_connected():
                daemon_status = {"status": "online", "online": True}
            else:
                daemon_status = {"status": "offline", "online": False}
        else:
            daemon_status = {"status": "not_configured", "online": False}

        item_status["daemon"] = daemon_status
        item_status["agent_route"] = {
            "status": "ok" if binding.allow_chat else "disabled",
            "chat_enabled": binding.allow_chat,
            "route_key": item_status["route_key"],
            "default_target": binding.is_default_target,
            "filtered_output_enabled": binding.receive_filtered_output,
        }
        items_status.append(item_status)

    result["chain"]["items"] = items_status

    all_ok = (
        robot.is_enabled
        and bridge_status.get("connected", False)
        and (not uses_napcat_socket or socket_status.get("connected", False))
        and any(item.get("daemon", {}).get("online", False) for item in items_status)
    )
    result["overall_status"] = "ok" if all_ok else "degraded"

    return result


@router.post("/{id}/reload")
def reload_robot_bridge(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> dict:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    success, detail = robot_bridge_client.notify_reload()
    if success:
        record_robot_event(
            str(id),
            direction="backend_to_bridge",
            event="manual_reload",
            message=detail,
        )
        return {"success": True, "message": detail}

    record_robot_event(
        str(id),
        direction="backend_to_bridge",
        event="manual_reload",
        status="error",
        message=detail,
    )
    return {"success": False, "error": detail}


@router.post("/{id}/debug/test-event")
def create_robot_debug_test_event(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> dict:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)
    record_robot_event(
        str(id),
        direction="backend",
        event="debug_test_event",
        message="Debug event pipeline is working",
        payload={"robot_name": robot.name},
    )
    return {"success": True}


@router.get("/{id}/debug")
def get_robot_debug(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    limit: int = 100,
) -> dict:
    import httpx

    from app.core.config import settings

    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    bridge_health: dict = {"status": "unknown"}
    try:
        response = httpx.get(
            f"{settings.ROBOT_BRIDGE_URL}/internal/health",
            headers={
                "X-TermMan-Bridge-Token": settings.ROBOT_BRIDGE_SHARED_SECRET
                or settings.SECRET_KEY
            },
            timeout=5.0,
        )
        response.raise_for_status()
        bridge_health = response.json()
    except Exception as e:
        bridge_health = {"status": "error", "error": str(e)}

    robot_health = bridge_health.get("robots", {}).get(str(id), {})
    onebot_socket = (
        robot_health.get("onebot_socket")
        if isinstance(robot_health.get("onebot_socket"), dict)
        else {}
    )
    connection_errors = bridge_health.get("connection_errors", {})
    raw_connection_error = connection_errors.get(str(id))
    historical_error = (
        raw_connection_error.get("message")
        if isinstance(raw_connection_error, dict)
        else raw_connection_error
    )
    connected = robot_health.get("connected", False)
    events = get_robot_events(str(id), limit=limit)
    return {
        "robot": {
            "id": str(robot.id),
            "name": robot.name,
            "platform": robot.platform,
            "provider": robot.provider,
            "is_enabled": robot.is_enabled,
            "app_id": robot.app_id,
        },
        "bridge": {
            "url": settings.ROBOT_BRIDGE_URL,
            "status": bridge_health.get(
                "status", "ok" if "error" not in bridge_health else "error"
            ),
            "loaded_robot_count": bridge_health.get("loaded_robot_count", 0),
            "connected_bot_count": bridge_health.get("connected_bot_count", 0),
            "connected": robot_health.get("connected", False),
            "identity": robot_health.get("identity"),
            "bot": robot_health.get("bot"),
            "bots": bridge_health.get("bots", []),
            "onebot_socket": onebot_socket,
            "checked_at": bridge_health.get("checked_at"),
            "last_platform_event_at": robot_health.get("last_platform_event_at"),
            "last_message_event_at": robot_health.get("last_message_event_at"),
            "error": None
            if connected
            else robot_health.get("error")
            or historical_error
            or bridge_health.get("error"),
            "stale_error": historical_error if connected else None,
        },
        "diagnostics": {
            "event_count": len(events),
            "last_event_at": events[0].get("timestamp") if events else None,
            "qq_event_hint": (
                "Bridge is connected, but no OneBot/NapCat message event has reached TermMan yet. "
                "Check the NapCat reverse WebSocket URL and whether the logged-in QQ account is receiving messages."
                if connected and not robot_health.get("last_message_event_at")
                else None
            ),
        },
        "events": events,
    }
