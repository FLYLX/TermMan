import sys, json
sys.path.insert(0, "/app/backend")

from app.services.agent.mcp.local_server import LocalMCPServer
server = LocalMCPServer()
tools = server.list_tools()
total_chars = len(json.dumps(tools, ensure_ascii=False))
print(f"MCP raw tools: {len(tools)} tools, {total_chars} chars (~{total_chars//4} tokens)")
print()
for t in sorted(tools, key=lambda x: len(json.dumps(x, ensure_ascii=False)), reverse=True):
    name = t.get("name", "?")
    desc = t.get("description", "")
    schema = json.dumps(t.get("inputSchema", {}), ensure_ascii=False)
    total = len(json.dumps(t, ensure_ascii=False))
    print(f"  {name}: total={total}, desc={len(desc)}, schema={len(schema)}")

# Now check how agent converts to litellm format
print("\n--- Checking agent tool conversion ---")
from app.services.agent.agent import Agent
import inspect
src = inspect.getsource(Agent.get_tools_for_litellm)
print(src[:500])