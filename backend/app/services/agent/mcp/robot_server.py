from __future__ import annotations

from app.plugins.robot.mcp.server import RobotMCPServer, robot_mcp_server

__all__ = ["RobotMCPServer", "robot_mcp_server"]


if __name__ == "__main__":
    import asyncio

    asyncio.run(robot_mcp_server.run())
