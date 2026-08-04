from app.services.agent.mcp.local_server import LocalMCPServer

server = LocalMCPServer()
result = server._read_terminal_log({"item_id": "ea52de0c-51b7-4b49-a43d-985ed2e09579", "tail_lines": 10})
for r in result:
    if r.get("type") == "text":
        print(r["text"][-500:])
