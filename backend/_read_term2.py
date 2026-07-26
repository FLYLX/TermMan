from app.services.agent.session import agent_session_manager
from app.services.agent.mcp.local_server import LocalMCPServer

item_id = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

# Try to read terminal log via MCP
server = LocalMCPServer()
result = server._read_terminal_log({"item_id": item_id, "tail_lines": 25})
for r in result:
    if r.get("type") == "text":
        print(r["text"][-800:])
