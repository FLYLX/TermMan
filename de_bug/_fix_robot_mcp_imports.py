import pathlib
p = pathlib.Path(r"E:\dev\TermMan\dev\TermMan\backend\tests\services\test_robot_mcp_server.py")
text = p.read_text(encoding="utf-8")
old1 = """from app.services.agent.mcp.robot_context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.mcp.robot_server import RobotMCPServer"""
new1 = """from app.plugins.robot.mcp.context import (
    RobotMCPContext,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.plugins.robot.mcp.server import RobotMCPServer"""
assert text.count(old1) == 1
text = text.replace(old1, new1)
p.write_text(text, encoding="utf-8")
print("imports fixed")
