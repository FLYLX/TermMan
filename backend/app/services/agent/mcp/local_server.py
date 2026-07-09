import asyncio
import json
import logging
import sys

logger = logging.getLogger(__name__)


def debug_log(msg: str):
    print(msg, file=sys.stderr, flush=True)


TERMINAL_NOT_CONNECTED_MESSAGE = "终端未连接或未打开，命令没有发送。请先启动或连接终端后再试。"


class LocalMCPServer:
    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        self.register_tool(
            name="execute_command",
            description="在终端执行 shell 命令",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"}
                },
                "required": ["command"]
            },
            handler=self._execute_command,
            skip_memory=True
        )
        
        self.register_tool(
            name="interrupt_command",
            description="发送 Ctrl+C 中断当前终端正在运行的命令",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=self._interrupt_command,
            skip_memory=True
        )
        
        self.register_tool(
            name="read_terminal_log",
            description="读取终端日志文件（原始输出），用于查看完整的错误信息或命令执行结果。",
            input_schema={
                "type": "object",
                "properties": {
                    "lines": {"type": "integer", "description": "读取最后 N 行，默认 64", "default": 64}
                },
                "required": []
            },
            handler=self._read_terminal_log,
            skip_memory=True
        )
        
        self.register_tool(
            name="list_installed_software",
            description="List software that has been recorded as installed for the current terminal item.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=self._list_installed_software,
            skip_memory=True
        )

        self.register_tool(
            name="record_installed_software",
            description="Record software as installed after terminal output confirms installation succeeded.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Software or package name"},
                    "manager": {"type": "string", "description": "Package manager or source, such as apt, pip, npm, bun, manual"},
                    "version": {"type": "string", "description": "Installed version if known"},
                    "command": {"type": "string", "description": "Command that installed it"},
                    "notes": {"type": "string", "description": "Short verification notes"}
                },
                "required": ["name"]
            },
            handler=self._record_installed_software,
            skip_memory=True
        )

        self.register_tool(
            name="remove_installed_software",
            description="Remove software from the recorded installed list after uninstall is confirmed.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Software or package name"},
                    "manager": {"type": "string", "description": "Package manager or source"},
                    "reason": {"type": "string", "description": "Why it was removed from the list"}
                },
                "required": ["name"]
            },
            handler=self._remove_installed_software,
            skip_memory=True
        )
        self.register_tool(
            name="save_memory",
            description="保存稳定、可复用、已验证的重要信息到长期记忆中。不要保存原生日志、命令回显、等待态消息或敏感信息。",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要保存的记忆内容"},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "记忆类型: fact(事实), preference(偏好), task(任务), error(错误), context(上下文)"},
                    "ttl_days": {"type": "integer", "description": "过期天数，默认 30 天", "default": 30}
                },
                "required": ["content"]
            },
            handler=self._save_memory
        )
        
        self.register_tool(
            name="recall_memory",
            description="从长期记忆中检索相关信息。使用语义搜索，返回与查询最相关的记忆。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或问题"},
                    "n_results": {"type": "integer", "description": "返回结果数量，默认 5", "default": 5},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "可选：限定记忆类型"}
                },
                "required": ["query"]
            },
            handler=self._recall_memory
        )
        
        self.register_tool(
            name="list_memories",
            description="列出所有记忆，可按类型过滤。",
            input_schema={
                "type": "object",
                "properties": {
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "可选：限定记忆类型"}
                },
                "required": []
            },
            handler=self._list_memories
        )
        
        self.register_tool(
            name="delete_memory",
            description="删除指定的记忆。",
            input_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "要删除的记忆 ID"}
                },
                "required": ["memory_id"]
            },
            handler=self._delete_memory
        )
    
    def register_tool(self, name: str, description: str, input_schema: dict, handler: callable, skip_memory: bool = False):
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler,
            "skip_memory": skip_memory
        }
    
    def _restore_existing_terminal_input(self, item_id: str) -> bool:
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item
            from app.services import DaemonConfig, connection_manager, socket_pool_facade
            from app.services.terminal_service import TerminalService

            try:
                item_uuid = uuid.UUID(str(item_id))
            except ValueError:
                debug_log(f"[LocalMCPServer] invalid item_id for restore: {item_id}")
                return False

            with Session(engine) as db:
                item = db.get(Item, item_uuid)
                if not item:
                    debug_log(f"[LocalMCPServer] item not found for restore: {item_id}")
                    return False
                if not item.socket_host or not item.socket_port or not item.api_key:
                    debug_log(f"[LocalMCPServer] item missing daemon config for restore: {item_id}")
                    return False

                daemon_config = DaemonConfig(item.socket_host, item.socket_port, item.api_key)
                owner_uuid = str(item.owner_id)

            connection = connection_manager.get_or_create_connection(daemon_config)
            if not connection.is_connected():
                debug_log(f"[LocalMCPServer] daemon not connected for restore: {item_id}")
                return False

            status_result = connection.terminal_status_http(str(item_id))
            if not status_result.get("success"):
                debug_log(
                    f"[LocalMCPServer] terminal status unavailable for restore: {item_id}, "
                    f"error={status_result.get('error')}"
                )
                return False

            status_data = status_result.get("data") or {}
            terminal_status = str(status_data.get("status") or "")
            token = status_data.get("token")
            if terminal_status not in {"running", "waiting_backend"} or not token:
                debug_log(
                    f"[LocalMCPServer] terminal not active for restore: {item_id}, "
                    f"status={terminal_status}, token={bool(token)}"
                )
                return False

            terminal_service = TerminalService(connection_manager, socket_pool_facade)
            restored = terminal_service.restore_terminal_session(
                item_uuid=str(item_id),
                owner_uuid=owner_uuid,
                daemon_config=daemon_config,
                token=str(token),
            )
            debug_log(f"[LocalMCPServer] terminal input restore result: item={item_id}, restored={restored}")
            return bool(restored)
        except Exception as exc:
            debug_log(f"[LocalMCPServer] terminal input restore error for item={item_id}: {exc}")
            return False

    def _ensure_terminal_input_handler(self, item_id: str) -> bool:
        from app.services.socket_pool.input_center import input_center

        if input_center.has_handler(item_id):
            return True
        if self._restore_existing_terminal_input(item_id):
            return input_center.has_handler(item_id)
        return False

    def _execute_command(self, args: dict) -> list:
        command = args.get("command", "")
        item_id = args.get("item_id", "")
        
        debug_log(f"[LocalMCPServer] _execute_command: item={item_id}, command={command}")
        
        if not command or not item_id:
            return [{"type": "text", "text": "Error: command and item_id required"}]
        
        try:
            from app.services.socket_pool import InputSDK
            has_handler = self._ensure_terminal_input_handler(item_id)
            debug_log(f"[LocalMCPServer] has_handler={has_handler}")
            if not has_handler:
                return [{"type": "text", "text": TERMINAL_NOT_CONNECTED_MESSAGE}]
            
            if not command.endswith("\n"):
                command = command + "\n"
            
            success = InputSDK().send(item_id, command)
            debug_log(f"[LocalMCPServer] send result: success={success}")
            
            return [
                {
                    "type": "text",
                    "text": (
                        f"命令已发送到终端，尚未确认执行结果: {command.strip()}"
                        if success
                        else TERMINAL_NOT_CONNECTED_MESSAGE
                    ),
                }
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] execute_command error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _interrupt_command(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        
        debug_log(f"[LocalMCPServer] _interrupt_command: item={item_id}")
        
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        
        try:
            from app.services.socket_pool import InputSDK
            has_handler = self._ensure_terminal_input_handler(item_id)
            debug_log(f"[LocalMCPServer] interrupt has_handler={has_handler}")
            if not has_handler:
                return [{"type": "text", "text": TERMINAL_NOT_CONNECTED_MESSAGE}]
            
            success = InputSDK().send(item_id, "\x03")
            debug_log(f"[LocalMCPServer] interrupt result: success={success}")
            
            return [
                {
                    "type": "text",
                    "text": (
                        "Ctrl+C 已发送到终端，是否已中断需等待后续输出确认"
                        if success
                        else "Ctrl+C 发送失败"
                    ),
                }
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] interrupt error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _read_terminal_log(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        lines = args.get("lines", 64)
        
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        
        try:
            from app.services.log_manager import LogManager
            content = LogManager().get_last_lines(item_id, lines)
            
            if not content:
                return [{"type": "text", "text": f"No log found for {item_id}"}]
            
            return [{"type": "text", "text": f"=== 终端日志 (最后 {lines} 行) ===\n{content}"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _list_installed_software(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]

        try:
            from app.services.agent.installed_software import (
                format_installed_software,
                list_installed_software,
            )

            items = list_installed_software(item_id)
            return [
                {
                    "type": "text",
                    "text": "Installed software list:\n" + format_installed_software(items),
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _record_installed_software(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        name = args.get("name", "")
        if not item_id or not name:
            return [{"type": "text", "text": "Error: item_id and name required"}]

        try:
            from app.services.agent.installed_software import record_installed_software

            item = record_installed_software(
                item_id,
                name=name,
                manager=args.get("manager", "unknown"),
                version=args.get("version", ""),
                command=args.get("command", ""),
                notes=args.get("notes", ""),
            )
            manager = item.get("manager", "unknown")
            version = item.get("version", "unknown")
            return [
                {
                    "type": "text",
                    "text": f"Recorded installed software: {item['name']} [{manager}], version={version}",
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _remove_installed_software(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        name = args.get("name", "")
        if not item_id or not name:
            return [{"type": "text", "text": "Error: item_id and name required"}]

        try:
            from app.services.agent.installed_software import remove_installed_software

            result = remove_installed_software(
                item_id,
                name=name,
                manager=args.get("manager", ""),
                reason=args.get("reason", ""),
            )
            count = result.get("count", 0)
            return [
                {
                    "type": "text",
                    "text": f"Removed {count} installed software record(s) for: {name}",
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _save_memory(self, args: dict) -> list:
        content = args.get("content", "")
        memory_type = args.get("memory_type", "fact")
        ttl_days = args.get("ttl_days", 30)
        item_id = args.get("item_id", "")
        
        if not content or not item_id:
            return [{"type": "text", "text": "Error: content and item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            memory_id = vector_store.add_memory(
                item_id=item_id,
                content=content,
                memory_type=memory_type,
                ttl_days=ttl_days
            )
            return [{"type": "text", "text": f"✓ 记忆已保存 (ID: {memory_id[:8]}..., 类型: {memory_type}, 有效期: {ttl_days}天)"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _recall_memory(self, args: dict) -> list:
        query = args.get("query", "")
        n_results = args.get("n_results", 5)
        memory_type = args.get("memory_type")
        item_id = args.get("item_id", "")
        
        if not query or not item_id:
            return [{"type": "text", "text": "Error: query and item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            results = vector_store.search_memories(
                item_id=item_id,
                query=query,
                n_results=n_results,
                memory_type=memory_type
            )
            
            if not results:
                return [{"type": "text", "text": "未找到相关记忆"}]
            
            lines = [f"=== 找到 {len(results)} 条相关记忆 ==="]
            for i, m in enumerate(results, 1):
                m_type = m.get("metadata", {}).get("memory_type", "unknown")
                distance = m.get("distance", 0)
                lines.append(f"\n[{i}] ({m_type}, 相关度: {1-distance:.2%})")
                lines.append(f"    {m['content']}")
            
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _list_memories(self, args: dict) -> list:
        memory_type = args.get("memory_type")
        item_id = args.get("item_id", "")
        
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            memories = vector_store.get_all_memories(item_id, memory_type=memory_type)
            
            if not memories:
                return [{"type": "text", "text": "暂无记忆"}]
            
            lines = [f"=== 共 {len(memories)} 条记忆 ==="]
            for m in memories:
                m_type = m.get("metadata", {}).get("memory_type", "unknown")
                m_id = m.get("id", "")[:8]
                lines.append(f"[{m_id}] ({m_type}) {m['content'][:50]}...")
            
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _delete_memory(self, args: dict) -> list:
        memory_id = args.get("memory_id", "")
        item_id = args.get("item_id", "")
        
        if not memory_id or not item_id:
            return [{"type": "text", "text": "Error: memory_id and item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            success = vector_store.delete_memory(memory_id)
            if success:
                return [{"type": "text", "text": f"✓ 记忆已删除 (ID: {memory_id[:8]}...)"}]
            else:
                return [{"type": "text", "text": f"记忆不存在或删除失败"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def list_tools(self) -> list:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
                "skip_memory": t.get("skip_memory", False)
            }
            for t in self._tools.values()
        ]
    
    def call_tool(self, name: str, args: dict) -> list:
        debug_log(f"[LocalMCPServer] call_tool: name={name}, args={args}")
        if name not in self._tools:
            debug_log(f"[LocalMCPServer] Tool '{name}' not found, available: {list(self._tools.keys())}")
            return [{"type": "text", "text": f"Tool '{name}' not found"}]
        try:
            result = self._tools[name]["handler"](args)
            debug_log(f"[LocalMCPServer] Tool '{name}' result: {result}")
            return result
        except Exception as e:
            debug_log(f"[LocalMCPServer] Tool '{name}' error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]
    
    async def run(self):
        logger.info("[LocalMCPServer] Starting stdio server")
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                request = json.loads(line.strip())
                response = await self._handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": f"Invalid JSON: {e}"}), flush=True)
            except Exception as e:
                print(json.dumps({"error": str(e)}), flush=True)
    
    async def _handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")
        
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "termman-local", "version": "1.0.0"}
            }}
        
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.list_tools()}}
        
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": self.call_tool(params.get("name", ""), params.get("arguments", {}))}}
        
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


local_mcp_server = LocalMCPServer()


def main():
    asyncio.run(local_mcp_server.run())


if __name__ == "__main__":
    main()
