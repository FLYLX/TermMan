import sys, json
sys.path.insert(0, "/app/backend")
# Force reimport
import importlib
import app.services.agent.mcp.local_server as ls
importlib.reload(ls)
server = ls.LocalMCPServer()
tools = server.list_tools()
total_chars = len(json.dumps(tools, ensure_ascii=False))
print(f"Tools: {len(tools)} tools, {total_chars} chars (~{total_chars//4} tokens)")
print(f"Before: 14585 chars. Saved: {14585 - total_chars} chars ({(14585-total_chars)*100//14585}%)")