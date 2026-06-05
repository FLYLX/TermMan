from __future__ import annotations

import asyncio
import json
import logging
import sys

from app.services.agent.mcp.robot_context import get_robot_mcp_context

logger = logging.getLogger(__name__)


class RobotMCPServer:
    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        self.register_tool(
            name="send_message",
            description=(
                "Send a concise message to the current NoneBot/NapCat conversation. "
                "Use this when your robot instructions say a QQ-side message should be "
                "delivered through the tool, or when an additional proactive robot-side "
                "update is needed. The target is always the current robot conversation; "
                "do not ask for or invent group IDs."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Message text to send to the current robot conversation.",
                    }
                },
                "required": ["text"],
            },
            handler=self._send_message,
            skip_memory=True,
        )

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: callable,
        skip_memory: bool = False,
    ) -> None:
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler,
            "skip_memory": skip_memory,
        }

    def _send_message(self, args: dict) -> list[dict[str, str]]:
        text = str(args.get("text") or "").strip()
        if not text:
            return [{"type": "text", "text": "Error: text required"}]

        context_token = str(args.get("_robot_context_token") or "").strip()
        context = get_robot_mcp_context(context_token)
        if context is None:
            return [
                {
                    "type": "text",
                    "text": (
                        "Error: no active robot conversation context. "
                        "This tool can only be used while handling a NoneBot/NapCat message."
                    ),
                }
            ]

        try:
            from app.plugins.robot.bridge_client import robot_bridge_client

            robot_bridge_client.send_message(
                context.robot_id,
                context.reply_target.model_copy(deep=True),
                text,
            )
            return [{"type": "text", "text": "Message sent to current robot conversation."}]
        except Exception as exc:
            logger.warning("[RobotMCPServer] Failed to send robot message: %s", exc)
            return [{"type": "text", "text": f"Error: {exc}"}]

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
                "skip_memory": tool.get("skip_memory", False),
            }
            for tool in self._tools.values()
        ]

    def call_tool(self, name: str, args: dict) -> list[dict[str, str]]:
        if name not in self._tools:
            return [{"type": "text", "text": f"Tool '{name}' not found"}]
        try:
            return self._tools[name]["handler"](args)
        except Exception as exc:
            logger.warning("[RobotMCPServer] Tool '%s' failed: %s", name, exc)
            return [{"type": "text", "text": f"Error: {exc}"}]

    async def run(self) -> None:
        logger.info("[RobotMCPServer] Starting stdio server")
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                request = json.loads(line.strip())
                response = await self._handle_request(request)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError as exc:
                sys.stdout.write(json.dumps({"error": f"Invalid JSON: {exc}"}) + "\n")
                sys.stdout.flush()
            except Exception as exc:
                sys.stdout.write(json.dumps({"error": str(exc)}) + "\n")
                sys.stdout.flush()

    async def _handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "termman-robot", "version": "1.0.0"},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": self.list_tools()},
            }

        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": self.call_tool(
                        params.get("name", ""),
                        params.get("arguments", {}),
                    )
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


robot_mcp_server = RobotMCPServer()


def main() -> None:
    asyncio.run(robot_mcp_server.run())


if __name__ == "__main__":
    main()
