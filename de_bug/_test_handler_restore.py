"""Simulate: handler unregistered while socket alive -> restore must re-register."""
from app.services.socket_pool.input_center import input_center
from app.services.socket_pool.socket_manager import SocketManager
from app.services.agent.mcp.local_server import local_mcp_server

ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

print("has_handler before:", input_center.has_handler(ITEM))

# simulate the failure: transient state check failure unregisters handlers
removed = input_center.unregister_all_by_item(ITEM)
print("unregistered:", removed)
print("has_handler after unregister:", input_center.has_handler(ITEM))

# socket still has stale _input_handler_id
from app.services import socket_pool_facade
sock = socket_pool_facade.get_backend_socket(ITEM)
print("socket exists:", bool(sock), "connected:", sock.is_connected() if sock else None)
print("stale _input_handler_id:", getattr(sock, "_input_handler_id", None))

# now the ensure path should restore
ok = local_mcp_server._ensure_terminal_input_handler(ITEM)
print("ensure result:", ok)
print("has_handler after restore:", input_center.has_handler(ITEM))
print("new handler id:", getattr(sock, "_input_handler_id", None) if sock else None)
