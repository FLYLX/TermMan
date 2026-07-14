from fastapi import APIRouter

from app.api.routes import (
    chat,
    item_handler_associations,
    item_handlers,
    items,
    knowledge,
    login,
    mcp,
    memory,
    pending_replies,
    plugins,
    private,
    skills,
    users,
    utils,
)
from app.core.config import settings
from app.services.plugins import plugin_manager

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(item_handlers.router)
api_router.include_router(item_handler_associations.router)
api_router.include_router(knowledge.router)
api_router.include_router(skills.router)
api_router.include_router(chat.router)
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(pending_replies.router)
api_router.include_router(mcp.router)
api_router.include_router(plugins.router)
plugin_manager.include_routers(api_router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
