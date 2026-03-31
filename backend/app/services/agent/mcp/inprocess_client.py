import json
import logging
from typing import Any

from .types import MCPTool

logger = logging.getLogger(__name__)


class InProcessMCPClient:
    def __init__(self, server_name: str, handler):
        self.server_name = server_name
        self._handler = handler
        self._request_id = 0
        self._initialized = False
        self._tools: list[MCPTool] = []
    
    async def start(self) -> bool:
        result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "TermMan", "version": "1.0.0"},
        })
        
        if result:
            self._initialized = True
            logger.info(f"[InProcessMCPClient] Initialized server '{self.server_name}'")
            return True
        return False
    
    async def stop(self):
        self._initialized = False
        self._tools = []
    
    async def _send_request(self, method: str, params: dict | None = None) -> dict | None:
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        
        try:
            response = await self._handler(request)
            
            if "error" in response:
                logger.error(f"[InProcessMCPClient] Error from server '{self.server_name}': {response['error']}")
                return None
            
            return response.get("result")
        except Exception as e:
            logger.error(f"[InProcessMCPClient] Error sending request to '{self.server_name}': {e}")
            return None
    
    async def initialize(self) -> bool:
        return await self.start()
    
    async def list_tools(self) -> list[MCPTool]:
        if not self._initialized:
            return []
        
        result = await self._send_request("tools/list")
        
        if not result or "tools" not in result:
            return []
        
        self._tools = []
        for tool_data in result["tools"]:
            tool = MCPTool(
                name=tool_data.get("name", ""),
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {}),
                server_name=self.server_name,
            )
            self._tools.append(tool)
        
        logger.info(f"[InProcessMCPClient] Found {len(self._tools)} tools in server '{self.server_name}'")
        return self._tools
    
    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        if not self._initialized:
            return {"error": "Server not initialized"}
        
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        
        if result:
            return result.get("content", [])
        return {"error": "Tool call failed"}
    
    def get_tools(self) -> list[MCPTool]:
        return self._tools
    
    @property
    def is_running(self) -> bool:
        return self._initialized
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized
