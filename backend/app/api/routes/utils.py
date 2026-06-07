import httpx
from fastapi import APIRouter, Depends
from pydantic.networks import EmailStr
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import Item, Message
from app.plugins.robot.bridge_client import robot_bridge_client
from app.services.runtime_monitor import (
    BackendRuntimeStatsResponse,
    TermManRuntimeStatsResponse,
    build_termman_runtime_response,
    collect_backend_runtime_stats,
    runtime_service_stats,
)
from app.utils import generate_test_email, send_email

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check() -> bool:
    return True


@router.get(
    "/backend-runtime/",
    response_model=BackendRuntimeStatsResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
def backend_runtime_stats() -> BackendRuntimeStatsResponse:
    return collect_backend_runtime_stats()


def _daemon_runtime_services(session: SessionDep) -> list:
    items = session.exec(select(Item)).all()
    daemons: dict[str, tuple[str, str]] = {}
    for item in items:
        if not item.socket_host or not item.socket_port or not item.api_key:
            continue
        daemon_url = f"http://{item.socket_host}:{item.socket_port}"
        daemon_key = f"{daemon_url}:{item.api_key}"
        daemons[daemon_key] = (daemon_url, item.api_key)

    services = []
    with httpx.Client(timeout=2.0) as client:
        for index, (daemon_url, api_key) in enumerate(daemons.values(), start=1):
            label = f"Daemon {index}" if len(daemons) > 1 else "Daemon"
            try:
                response = client.get(
                    f"{daemon_url.rstrip('/')}/api/runtime",
                    headers={"X-API-Key": api_key},
                )
                response.raise_for_status()
                payload = response.json()
                services.append(
                    runtime_service_stats(
                        service=f"daemon:{index}",
                        label=label,
                        kind="daemon",
                        runtime=payload,
                        url=daemon_url,
                        metadata={"daemon_url": daemon_url},
                    )
                )
            except Exception as exc:
                services.append(
                    runtime_service_stats(
                        service=f"daemon:{index}",
                        label=label,
                        kind="daemon",
                        status="error",
                        url=daemon_url,
                        error=str(exc),
                        metadata={"daemon_url": daemon_url},
                    )
                )
    return services


def _robot_runtime_service() -> list:
    try:
        bridge_health = robot_bridge_client.get_health(timeout=2.0)
        runtime = bridge_health.get("runtime")
        if isinstance(runtime, dict):
            return [
                runtime_service_stats(
                    service="robot",
                    label="Robot Bridge",
                    kind="robot",
                    runtime=runtime,
                    url=robot_bridge_client.base_url,
                    metadata={
                        "loaded_robot_count": bridge_health.get("loaded_robot_count", 0),
                        "connected_bot_count": bridge_health.get(
                            "connected_bot_count", 0
                        ),
                    },
                )
            ]
        return [
            runtime_service_stats(
                service="robot",
                label="Robot Bridge",
                kind="robot",
                status="error",
                url=robot_bridge_client.base_url,
                error="Robot bridge did not report runtime metrics",
            )
        ]
    except Exception as exc:
        return [
            runtime_service_stats(
                service="robot",
                label="Robot Bridge",
                kind="robot",
                status="error",
                url=robot_bridge_client.base_url,
                error=str(exc),
            )
        ]


@router.get(
    "/termman-runtime/",
    response_model=TermManRuntimeStatsResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
def termman_runtime_stats(session: SessionDep) -> TermManRuntimeStatsResponse:
    services = [
        runtime_service_stats(
            service="backend",
            label="Backend API",
            kind="backend",
            runtime=collect_backend_runtime_stats(),
        )
    ]
    services.extend(_daemon_runtime_services(session))
    services.extend(_robot_runtime_service())
    return build_termman_runtime_response(services)
