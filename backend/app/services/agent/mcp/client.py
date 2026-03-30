import asyncio
import json
import logging
from typing import Any

from .types import MCPServer, MCPTool, MCPResource

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(self, server: MCPServer):
        self.server = server
        self.process: asyncio.subprocess.Process | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._request_id = 0
        self._initialized = False
        self._tools: list[MCPTool] = []
        self._resources: list[MCPResource] = []
    
    async def start(self) -> bool:
        try:
            env = dict(__import__("os").environ)
            env.update(self.server.env)
            
            self.process = await asyncio.create_subprocess_exec(
                self.server.command,
                *self.server.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            
            self.reader = self.process.stdout
            self.writer = self.process.stdin
            
            logger.info(f"[MCPClient] Started server '{self.server.name}' (PID: {self.process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"[MCPClient] Failed to start server '{self.server.name}': {e}")
            return False
    
    async def stop(self):
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.warning(f"[MCPClient] Error stopping server '{self.server.name}': {e}")
            
            self.process = None
            self.reader = None
            self.writer = None
            self._initialized = False
            logger.info(f"[MCPClient] Stopped server '{self.server.name}'")
    
    async def _send_request(self, method: str, params: dict | None = None) -> dict | None:
        if not self.writer or not self.reader:
            logger.error(f"[MCPClient] Server '{self.server.name}' not started")
            return None
        
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        
        try:
            message = json.dumps(request) + "\n"
            self.writer.write(message.encode())
            await self.writer.drain()
            
            response_line = await asyncio.wait_for(
                self.reader.readline(),
                timeout=30
            )
            
            if not response_line:
                logger.error(f"[MCPClient] Empty response from server '{self.server.name}'")
                return None
            
            response = json.loads(response_line.decode())
            
            if "error" in response:
                logger.error(f"[MCPClient] Error from server '{self.server.name}': {response['error']}")
                return None
            
            return response.get("result")
            
        except asyncio.TimeoutError:
            logger.error(f"[MCPClient] Timeout waiting for response from '{self.server.name}'")
            return None
        except Exception as e:
            logger.error(f"[MCPClient] Error sending request to '{self.server.name}': {e}")
            return None
    
    async def initialize(self) -> bool:
        result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
            },
            "clientInfo": {
                "name": "TermMan",
                "version": "1.0.0",
            },
        })
        
        if result:
            self._initialized = True
            logger.info(f"[MCPClient] Initialized server '{self.server.name}'")
            return True
        
        return False
    
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
                server_name=self.server.name,
            )
            self._tools.append(tool)
        
        logger.info(f"[MCPClient] Found {len(self._tools)} tools in server '{self.server.name}'")
        return self._tools
    
    async def list_resources(self) -> list[MCPResource]:
        if not self._initialized:
            return []
        
        result = await self._send_request("resources/list")
        
        if not result or "resources" not in result:
            return []
        
        self._resources = []
        for res_data in result["resources"]:
            resource = MCPResource(
                uri=res_data.get("uri", ""),
                name=res_data.get("name", ""),
                description=res_data.get("description", ""),
                mime_type=res_data.get("mimeType", ""),
                server_name=self.server.name,
            )
            self._resources.append(resource)
        
        logger.info(f"[MCPClient] Found {len(self._resources)} resources in server '{self.server.name}'")
        return self._resources
    
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
    
    async def read_resource(self, uri: str) -> Any:
        if not self._initialized:
            return {"error": "Server not initialized"}
        
        result = await self._send_request("resources/read", {
            "uri": uri,
        })
        
        return result
    
    def get_tools(self) -> list[MCPTool]:
        return self._tools
    
    def get_resources(self) -> list[MCPResource]:
        return self._resources
    
    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized and self.is_running
