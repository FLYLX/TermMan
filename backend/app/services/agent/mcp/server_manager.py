import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from .client import MCPClient
from .types import MCPServer, MCPTool, MCPResource

logger = logging.getLogger(__name__)


class MCPServerManager:
    CONFIG_FILE = "mcp_servers.json"
    
    def __init__(self, config_dir: Path | None = None):
        if config_dir is None:
            import os
            if os.path.exists("/app/mcp_servers.json"):
                config_dir = Path("/app")
            else:
                config_dir = Path(__file__).parent.parent.parent.parent.parent
        
        self.config_dir = Path(config_dir)
        self._servers: dict[str, MCPServer] = {}
        self._clients: dict[str, MCPClient] = {}
        self._load_config()
    
    def _load_config(self):
        config_file = self.config_dir / self.CONFIG_FILE
        if not config_file.exists():
            logger.info(f"[MCPServerManager] Config file not found: {config_file}")
            return
        
        try:
            with open(config_file, encoding="utf-8") as f:
                config = json.load(f)
            
            servers_data = config.get("mcpServers", {})
            for name, server_config in servers_data.items():
                server = MCPServer(
                    name=name,
                    command=server_config.get("command", ""),
                    args=server_config.get("args", []),
                    env=server_config.get("env", {}),
                    enabled=server_config.get("enabled", True),
                    description=server_config.get("description", ""),
                )
                self._servers[name] = server
            
            logger.info(f"[MCPServerManager] Loaded {len(self._servers)} MCP servers from config")
            
        except Exception as e:
            logger.error(f"[MCPServerManager] Failed to load config: {e}")
    
    def get_server(self, name: str) -> MCPServer | None:
        return self._servers.get(name)
    
    def get_all_servers(self) -> list[MCPServer]:
        return list(self._servers.values())
    
    def get_enabled_servers(self) -> list[MCPServer]:
        return [s for s in self._servers.values() if s.enabled]
    
    async def start_server(self, name: str) -> bool:
        server = self._servers.get(name)
        if not server:
            logger.warning(f"[MCPServerManager] Server '{name}' not found")
            return False
        
        if name in self._clients:
            client = self._clients[name]
            if client.is_running:
                logger.info(f"[MCPServerManager] Server '{name}' already running")
                return True
        
        logger.info(f"[MCPServerManager] Starting server '{name}': {server.command} {' '.join(server.args)}")
        
        client = MCPClient(server)
        if not await client.start():
            logger.error(f"[MCPServerManager] Failed to start process for '{name}'")
            return False
        
        if not await client.initialize():
            logger.error(f"[MCPServerManager] Failed to initialize '{name}'")
            await client.stop()
            return False
        
        tools = await client.list_tools()
        await client.list_resources()
        
        self._clients[name] = client
        logger.info(f"[MCPServerManager] Server '{name}' started with {len(tools)} tools")
        return True
    
    async def stop_server(self, name: str):
        if name in self._clients:
            await self._clients[name].stop()
            del self._clients[name]
    
    async def start_all(self):
        for server in self.get_enabled_servers():
            await self.start_server(server.name)
    
    async def stop_all(self):
        for name in list(self._clients.keys()):
            await self.stop_server(name)
    
    def get_client(self, name: str) -> MCPClient | None:
        return self._clients.get(name)
    
    def get_all_tools(self) -> list[MCPTool]:
        tools = []
        for client in self._clients.values():
            tools.extend(client.get_tools())
        return tools
    
    def get_tools_for_server(self, server_name: str) -> list[MCPTool]:
        client = self._clients.get(server_name)
        return client.get_tools() if client else []
    
    def get_all_resources(self) -> list[MCPResource]:
        resources = []
        for client in self._clients.values():
            resources.extend(client.get_resources())
        return resources
    
    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Any:
        client = self._clients.get(server_name)
        if not client:
            return {"error": f"Server '{server_name}' not running"}
        
        return await client.call_tool(tool_name, arguments)
    
    async def read_resource(self, server_name: str, uri: str) -> Any:
        client = self._clients.get(server_name)
        if not client:
            return {"error": f"Server '{server_name}' not running"}
        
        return await client.read_resource(uri)
    
    def reload_config(self):
        self._servers.clear()
        self._load_config()
    
    def _save_config(self):
        config_file = self.config_dir / self.CONFIG_FILE
        
        config = {"mcpServers": {}}
        for name, server in self._servers.items():
            config["mcpServers"][name] = {
                "command": server.command,
                "args": server.args,
                "env": server.env,
                "enabled": server.enabled,
                "description": server.description,
            }
        
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[MCPServerManager] Saved {len(self._servers)} MCP servers to config")
    
    def add_server(
        self,
        name: str,
        command: str,
        args: list[str] = None,
        env: dict[str, str] = None,
        enabled: bool = True,
        description: str = "",
    ):
        if name in self._servers:
            raise ValueError(f"Server '{name}' already exists")
        
        server = MCPServer(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            enabled=enabled,
            description=description,
        )
        self._servers[name] = server
        self._save_config()
        logger.info(f"[MCPServerManager] Added MCP server '{name}'")
    
    def update_server(
        self,
        name: str,
        command: str = None,
        args: list[str] = None,
        env: dict[str, str] = None,
        enabled: bool = None,
        description: str = None,
    ):
        server = self._servers.get(name)
        if not server:
            raise ValueError(f"Server '{name}' not found")
        
        if command is not None:
            server.command = command
        if args is not None:
            server.args = args
        if env is not None:
            server.env = env
        if enabled is not None:
            server.enabled = enabled
        if description is not None:
            server.description = description
        
        self._save_config()
        logger.info(f"[MCPServerManager] Updated MCP server '{name}'")
    
    def delete_server(self, name: str):
        if name not in self._servers:
            raise ValueError(f"Server '{name}' not found")
        
        del self._servers[name]
        self._save_config()
        logger.info(f"[MCPServerManager] Deleted MCP server '{name}'")
    
    def is_server_running(self, name: str) -> bool:
        client = self._clients.get(name)
        return client is not None and client.is_running


mcp_server_manager = MCPServerManager()
