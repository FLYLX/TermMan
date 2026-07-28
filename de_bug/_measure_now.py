import sys, json
sys.path.insert(0, "/app/backend")
from app.services.agent.mcp.local_server import LocalMCPServer
server = LocalMCPServer()
tools = server.list_tools()
total_chars = len(json.dumps(tools, ensure_ascii=False))
print(f"Tools: {len(tools)} tools, {total_chars} chars (~{total_chars//4} tokens)")
print()
for t in sorted(tools, key=lambda x: len(json.dumps(x, ensure_ascii=False)), reverse=True)[:10]:
    name = t.get("name", "?")
    total = len(json.dumps(t, ensure_ascii=False))
    desc = len(t.get("description", ""))
    schema = len(json.dumps(t.get("inputSchema", {}), ensure_ascii=False))
    print(f"  {name}: total={total}, desc={desc}, schema={schema}")