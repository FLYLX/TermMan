import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from app.services.agent.mcp.server_manager import mcp_server_manager
from app.api.deps import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


class MCPServerItem(BaseModel):
    name: str
    command: str
    args: list[str]
    env: dict[str, str]
    enabled: bool
    description: str


class MCPServerListResponse(BaseModel):
    data: list[MCPServerItem]
    count: int


class MCPServerCreateBody(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    enabled: bool = True
    description: str = ""


class MCPServerUpdateBody(BaseModel):
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    enabled: bool | None = None
    description: str | None = None


@router.get("/servers", response_model=MCPServerListResponse)
def list_mcp_servers(current_user: CurrentUser):
    servers = mcp_server_manager.get_all_servers()
    return MCPServerListResponse(
        data=[
            MCPServerItem(
                name=s.name,
                command=s.command,
                args=s.args,
                env=s.env,
                enabled=s.enabled,
                description=s.description,
            )
            for s in servers
        ],
        count=len(servers),
    )


@router.get("/servers/{server_name}", response_model=MCPServerItem)
def get_mcp_server(server_name: str, current_user: CurrentUser):
    server = mcp_server_manager.get_server(server_name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP Server '{server_name}' not found")
    
    return MCPServerItem(
        name=server.name,
        command=server.command,
        args=server.args,
        env=server.env,
        enabled=server.enabled,
        description=server.description,
    )


@router.post("/servers", response_model=MCPServerItem)
def create_mcp_server(current_user: CurrentUser, body: MCPServerCreateBody):
    if mcp_server_manager.get_server(body.name):
        raise HTTPException(status_code=400, detail=f"MCP Server '{body.name}' already exists")
    
    try:
        mcp_server_manager.add_server(
            name=body.name,
            command=body.command,
            args=body.args,
            env=body.env,
            enabled=body.enabled,
            description=body.description,
        )
        server = mcp_server_manager.get_server(body.name)
        return MCPServerItem(
            name=server.name,
            command=server.command,
            args=server.args,
            env=server.env,
            enabled=server.enabled,
            description=server.description,
        )
    except Exception as e:
        logger.error(f"[MCP] Failed to create server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/servers/{server_name}", response_model=MCPServerItem)
def update_mcp_server(server_name: str, current_user: CurrentUser, body: MCPServerUpdateBody):
    server = mcp_server_manager.get_server(server_name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP Server '{server_name}' not found")
    
    try:
        mcp_server_manager.update_server(
            name=server_name,
            command=body.command,
            args=body.args,
            env=body.env,
            enabled=body.enabled,
            description=body.description,
        )
        server = mcp_server_manager.get_server(server_name)
        return MCPServerItem(
            name=server.name,
            command=server.command,
            args=server.args,
            env=server.env,
            enabled=server.enabled,
            description=server.description,
        )
    except Exception as e:
        logger.error(f"[MCP] Failed to update server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/servers/{server_name}")
def delete_mcp_server(server_name: str, current_user: CurrentUser):
    server = mcp_server_manager.get_server(server_name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP Server '{server_name}' not found")
    
    try:
        mcp_server_manager.delete_server(server_name)
        return {"message": f"MCP Server '{server_name}' deleted successfully"}
    except Exception as e:
        logger.error(f"[MCP] Failed to delete server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
def reload_mcp_servers(current_user: CurrentUser):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only superusers can reload MCP servers")
    
    mcp_server_manager.reload_config()
    return {"message": f"Reloaded {len(mcp_server_manager.get_all_servers())} MCP servers"}
