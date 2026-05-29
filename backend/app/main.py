import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

import sentry_sdk
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.services import initialize_daemon_connections

logger = logging.getLogger(__name__)

_bridge_router_included = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bridge_router_included

    if settings.ROBOT_PLUGIN_ENABLED and settings.ROBOT_BRIDGE_EMBEDDED:
        from app.plugins.robot.bridge.embedded import (
            get_bridge_router,
            init_embedded_bridge,
            start_embedded_bridge,
            stop_embedded_bridge,
        )

        logger.info("[App] Initializing embedded robot bridge...")
        init_embedded_bridge()
        bridge_router = get_bridge_router()
        if bridge_router and not _bridge_router_included:
            app.include_router(bridge_router)
            _bridge_router_included = True
            logger.info("[App] Robot bridge router included")
        if bridge_router:
            logger.info("[App] Robot bridge initialized")
        await start_embedded_bridge()
    else:
        stop_embedded_bridge = None

    initialize_daemon_connections()

    from app.services.agent.mcp import mcp_server_manager
    logger.info("[App] Starting MCP servers...")
    await mcp_server_manager.start_all()
    logger.info("[App] MCP servers started")
    
    yield
    
    if stop_embedded_bridge is not None:
        await stop_embedded_bridge()

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
