import logging
import os
import threading
import time
from contextlib import asynccontextmanager

MEMORY_LIMIT_MB = 1024
MEMORY_CHECK_INTERVAL = 300


def _memory_watchdog():
    import resource
    while True:
        time.sleep(MEMORY_CHECK_INTERVAL)
        try:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            if rss > MEMORY_LIMIT_MB:
                logging.getLogger(__name__).warning(
                    "[App] Memory watchdog: RSS=%.0fMB > limit=%dMB, restarting", rss, MEMORY_LIMIT_MB
                )
                os._exit(0)
        except Exception:
            pass


def _start_memory_watchdog():
    t = threading.Thread(target=_memory_watchdog, name="memory-watchdog", daemon=True)
    t.start()

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.services import initialize_daemon_connections
from app.services.plugins import plugin_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await plugin_manager.startup(app)

    initialize_daemon_connections()

    from app.services.agent.mcp import mcp_server_manager

    logger.info("[App] Starting MCP servers...")
    await mcp_server_manager.start_all()
    logger.info("[App] MCP servers started")

    from app.services.agent.state_restore import restore_agent_state
    from app.services.agent.task_watchdog import agent_task_watchdog

    restore_agent_state()
    agent_task_watchdog.start()

    from app.services.agent.scheduled_tasks import scheduled_task_manager

    scheduled_task_manager.start()

    _start_memory_watchdog()

    yield

    scheduled_task_manager.stop()
    agent_task_watchdog.stop()

    await plugin_manager.shutdown(app)

    logger.info("[App] Stopping MCP servers...")
    await mcp_server_manager.stop_all()
    logger.info("[App] MCP servers stopped")


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.ENVIRONMENT == "local":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
elif settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)


# 注意：已移除每次请求后更新daemon连接池表的中间件
# 改为在start和stop操作中只同步特定item的连接表，减少不必要的数据传输
# 仍保留定时同步功能
