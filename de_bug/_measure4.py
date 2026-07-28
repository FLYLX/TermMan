import sys, json
sys.path.insert(0, "/app/backend")

# Find the MCP server class
import inspect
from app.services.agent.mcp import local_server
classes = [name for name, obj in inspect.getmembers(local_server, inspect.isclass)]
print("Classes in local_server:", classes)

# Check how agent builds tools
from app.services.agent.agent import Agent
src = inspect.getsource(Agent.__init__)
# Find where _mcp_tools is set
for line in src.split("\n"):
    if "_mcp_tools" in line or "mcp_tool" in line.lower():
        print(f"  {line.strip()}")