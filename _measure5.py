import sys, json
sys.path.insert(0, "/app/backend")

from app.services.agent.mcp.local_server import LocalMCPServer
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
server = LocalMCPServer(ITEM)
tools = server.list_tools()
total_chars = len(json.dumps(tools, ensure_ascii=False))
print(f"MCP Tools: {len(tools)} tools, {total_chars} chars total (~{total_chars//4} tokens)")
print()
for t in sorted(tools, key=lambda x: len(json.dumps(x, ensure_ascii=False)), reverse=True):
    name = t.get("name", "?")
    desc = t.get("description", "")
    schema = json.dumps(t.get("inputSchema", {}), ensure_ascii=False)
    total = len(json.dumps(t, ensure_ascii=False))
    print(f"  {name}: total={total}, desc={len(desc)}, schema={len(schema)}")