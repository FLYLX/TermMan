from fastapi import APIRouter

from app.api.routes import items, item_handlers, item_handler_associations, login, private, users, utils, skills, chat, memory, mcp
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(item_handlers.router)
api_router.include_router(item_handler_associations.router)
api_router.include_router(skills.router)
api_router.include_router(chat.router)
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(mcp.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
