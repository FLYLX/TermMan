import asyncio
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


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
                    "command": {"type": "string", "description": "要执行的命令"},
                    "item_id": {"type": "string", "description": "目标终端 ID"}
                },
                "required": ["command", "item_id"]
            },
            handler=self._execute_command
        )
        
        self.register_tool(
            name="read_terminal_log",
            description="读取终端日志文件（原始输出），用于查看完整的错误信息或命令执行结果。",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "目标终端 ID"},
                    "lines": {"type": "integer", "description": "读取最后 N 行，默认 64", "default": 64}
                },
                "required": ["item_id"]
            },
            handler=self._read_terminal_log
        )
        
        self.register_tool(
            name="read_file",
            description="读取文件内容",
            input_schema={
                "type": "object",
                "properties": {"file_path": {"type": "string", "description": "文件路径"}},
                "required": ["file_path"]
            },
            handler=self._read_file
        )
        
        self.register_tool(
            name="write_file",
            description="写入文件内容",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件内容"}
                },
                "required": ["file_path", "content"]
            },
            handler=self._write_file
        )
        
        self.register_tool(
            name="save_memory",
            description="保存重要信息到长期记忆中，用于记住用户偏好、项目配置、重要事实等。支持设置过期时间。",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要保存的记忆内容"},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "记忆类型: fact(事实), preference(偏好), task(任务), error(错误), context(上下文)"},
                    "ttl_days": {"type": "integer", "description": "过期天数，默认 30 天", "default": 30},
                    "item_id": {"type": "string", "description": "目标终端 ID"}
                },
                "required": ["content", "item_id"]
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
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "可选：限定记忆类型"},
                    "item_id": {"type": "string", "description": "目标终端 ID"}
                },
                "required": ["query", "item_id"]
            },
            handler=self._recall_memory
        )
        
        self.register_tool(
            name="list_memories",
            description="列出所有记忆，可按类型过滤。",
            input_schema={
                "type": "object",
                "properties": {
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "可选：限定记忆类型"},
                    "item_id": {"type": "string", "description": "目标终端 ID"}
                },
                "required": ["item_id"]
            },
            handler=self._list_memories
        )
        
        self.register_tool(
            name="delete_memory",
            description="删除指定的记忆。",
            input_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "要删除的记忆 ID"},
                    "item_id": {"type": "string", "description": "目标终端 ID"}
                },
                "required": ["memory_id", "item_id"]
            },
            handler=self._delete_memory
        )
    
    def register_tool(self, name: str, description: str, input_schema: dict, handler: callable):
        self._tools[name] = {"name": name, "description": description, "inputSchema": input_schema, "handler": handler}
    
    def _execute_command(self, args: dict) -> list:
        command = args.get("command", "")
        item_id = args.get("item_id", "")
        
        if not command or not item_id:
            return [{"type": "text", "text": "Error: command and item_id required"}]
        
        try:
            from app.services.socket_pool import InputSDK
            success = InputSDK().send(item_id, command)
            return [{"type": "text", "text": f"Command sent: {command}" if success else "Failed to send command"}]
        except Exception as e:
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
    
    def _read_file(self, args: dict) -> list:
        file_path = args.get("file_path", "")
        if not file_path:
            return [{"type": "text", "text": "Error: file_path required"}]
        
        try:
            path = Path(file_path)
            if not path.exists():
                return [{"type": "text", "text": f"File not found: {file_path}"}]
            return [{"type": "text", "text": path.read_text(encoding="utf-8")}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _write_file(self, args: dict) -> list:
        file_path = args.get("file_path", "")
        content = args.get("content", "")
        if not file_path:
            return [{"type": "text", "text": "Error: file_path required"}]
        
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return [{"type": "text", "text": f"File written: {file_path}"}]
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
        return [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]} for t in self._tools.values()]
    
    def call_tool(self, name: str, args: dict) -> list:
        if name not in self._tools:
            return [{"type": "text", "text": f"Tool '{name}' not found"}]
        try:
            return self._tools[name]["handler"](args)
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    async def run(self):
        logger.info("[LocalMCPServer] Starting stdio server")
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
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
